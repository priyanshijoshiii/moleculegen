import hashlib
import logging
import math
import os
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pydantic import BaseModel, Field
from rdkit import Chem
from rdkit.Chem import AllChem, BRICS, Descriptors, QED, rdMolDescriptors

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except Exception as exc:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    AutoModelForCausalLM = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]
    _learned_model_import_error = exc
else:
    _learned_model_import_error = None


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("uvicorn")

# Allow local .env.local values without requiring shell export.
# First preference is backend/.env.local (cwd = backend), then parent fallback.
load_dotenv(dotenv_path=".env.local", override=False)
load_dotenv(dotenv_path="../.env.local", override=False)

# Suppress Hugging Face symlinks warning on Windows (cache still works without symlinks).
if "HF_HUB_DISABLE_SYMLINKS_WARNING" not in os.environ:
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def _first_valid_env(*keys: str) -> Optional[str]:
    placeholders = {
        "<username>",
        "<password>",
        "<cluster-url>",
        "username",
        "password",
        "cluster-url",
    }

    for key in keys:
        value = os.getenv(key)
        if not value:
            continue

        lowered = value.strip().lower()
        if any(token in lowered for token in placeholders):
            continue
        return value

    return None

DEFAULT_GENERATOR_BACKEND = os.getenv("GENERATOR_BACKEND", "learned").strip().lower()
LEARNED_MODEL_NAME = os.getenv(
    "LEARNED_MODEL_NAME",
    "chandar-lab/NovoMolGen_32M_SMILES_BPE",
)
LEARNED_MODEL_REVISION = os.getenv("LEARNED_MODEL_REVISION", "hf-checkpoint")
LEARNED_BATCH_SIZE = max(1, int(os.getenv("LEARNED_MODEL_BATCH_SIZE", "16")))
LEARNED_MAX_NEW_TOKENS = max(24, int(os.getenv("LEARNED_MODEL_MAX_NEW_TOKENS", "96")))
LEARNED_PRELOAD = os.getenv("LEARNED_PRELOAD", "true").strip().lower() not in {"0", "false", "no"}
MONGO_URI = _first_valid_env("MONGODB_ATLAS_URI", "MONGODB_URI", "MONGO_URI") or "mongodb://127.0.0.1:27017"
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "molgen")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "generated_molecules")
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "10000"))
MONGO_ENABLED = os.getenv("MONGO_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
ALLOWED_ORIGIN_REGEX = os.getenv("ALLOWED_ORIGIN_REGEX", "").strip() or None


@dataclass(frozen=True)
class SeedRecord:
    name: str
    smiles: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DescriptorBundle:
    qed: float
    logp: float
    tpsa: float
    mw: float
    lipinski: int


@dataclass(frozen=True)
class GenerationRun:
    backend: str
    model_name: Optional[str]
    attempted_count: int
    valid_count: int
    molecules: List["MoleculeResult"]


class GenerateRequest(BaseModel):
    prompt: Optional[str] = ""
    qed: float = Field(ge=0.0, le=1.0)
    logp: float = Field(ge=-2.0, le=8.0)
    tpsa: float = Field(ge=0.0, le=250.0)
    mw: float = Field(ge=50.0, le=800.0)
    n: int = Field(default=50, ge=10, le=200)
    top_k: int = Field(default=5, ge=1, le=20)


class MoleculeResult(BaseModel):
    smiles: str
    sdf_string: Optional[str]
    qed: float
    logp: float
    tpsa: float
    mw: float
    lipinski: int
    reward_score: float


class GenerateResponse(BaseModel):
    prompt: str
    generator_backend: str
    generator_model: Optional[str]
    attempted_count: int
    valid_count: int
    returned_count: int
    validity_pct: float
    molecules: List[MoleculeResult]


def _cors_origins() -> tuple[List[str], bool, Optional[str]]:
    raw = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
    )
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if not origins:
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
    return origins, origins != ["*"], ALLOWED_ORIGIN_REGEX


@lru_cache(maxsize=1)
def _get_mongo_collection() -> Any | None:
    if not MONGO_ENABLED:
        return None

    try:
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
            appname="MolGen",
        )
        client.admin.command("ping")
        return client[MONGO_DB_NAME][MONGO_COLLECTION_NAME]
    except PyMongoError as exc:
        redacted_uri = MONGO_URI
        if "@" in redacted_uri and "://" in redacted_uri:
            prefix, suffix = redacted_uri.split("://", 1)
            if "@" in suffix:
                after_at = suffix.split("@", 1)[1]
                redacted_uri = f"{prefix}://***:***@{after_at}"
        logger.warning(
            "MongoDB unavailable for URI '%s'; generation results will not be persisted. Error: %s",
            redacted_uri,
            exc,
        )
        return None


def _store_generation_record(request: GenerateRequest, generation: GenerationRun, validity_pct: float):
    collection = _get_mongo_collection()
    if collection is None:
        return

    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": request.prompt or "",
        "generator_backend": generation.backend,
        "generator_model": generation.model_name,
        "request": {
            "qed": request.qed,
            "logp": request.logp,
            "tpsa": request.tpsa,
            "mw": request.mw,
            "n": request.n,
            "top_k": request.top_k,
        },
        "attempted_count": generation.attempted_count,
        "valid_count": generation.valid_count,
        "returned_count": len(generation.molecules),
        "validity_pct": validity_pct,
        "molecules": [molecule.model_dump() for molecule in generation.molecules],
    }

    try:
        collection.insert_one(document)
    except PyMongoError as exc:
        logger.warning("Failed to persist generation result to MongoDB: %s", exc)


def _warm_generation_backend():
    if DEFAULT_GENERATOR_BACKEND == "fragment":
        logger.info("GENERATOR_BACKEND=fragment; skipping learned model preload.")
    elif DEFAULT_GENERATOR_BACKEND != "learned":
        logger.warning(
            "GENERATOR_BACKEND=%s is unsupported; using fragment backend.",
            DEFAULT_GENERATOR_BACKEND,
        )
    elif LEARNED_PRELOAD:
        try:
            _load_learned_model()
            logger.info("Learned model preloaded: %s", LEARNED_MODEL_NAME)
        except Exception as exc:  # pragma: no cover
            logger.warning("Learned model preload failed. Error: %s", exc)
    else:
        logger.info("LEARNED_PRELOAD disabled; learned model will load on first request.")

    if MONGO_ENABLED:
        if _get_mongo_collection() is not None:
            logger.info(
                "MongoDB connected: %s/%s",
                MONGO_DB_NAME,
                MONGO_COLLECTION_NAME,
            )
    else:
        logger.info("MongoDB persistence disabled via MONGO_ENABLED")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warm_generation_backend()
    yield


app = FastAPI(title="MolGen Backend", version="1.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


origins, allow_credentials, allow_origin_regex = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


SEED_LIBRARY: tuple[SeedRecord, ...] = (
    SeedRecord("aspirin", "CC(=O)OC1=CC=CC=C1C(=O)O", ("oral", "aromatic")),
    SeedRecord("acetaminophen", "CC(=O)NC1=CC=C(O)C=C1", ("oral", "aromatic")),
    SeedRecord("ibuprofen", "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O", ("oral", "lipophilic")),
    SeedRecord("nicotinamide", "NC(=O)C1=CN=CC=C1", ("polar", "heterocycle")),
    SeedRecord("caffeine", "Cn1c(=O)c2c(ncn2C)n(C)c1=O", ("cns", "heterocycle")),
    SeedRecord("nicotine", "CN1CCC[C@H]1c2cccnc2", ("cns", "amine")),
    SeedRecord("metformin", "CN(C)C(=N)NC(=N)N", ("polar", "amine")),
    SeedRecord("isoniazid", "NNC(=O)C1=CC=NC=C1", ("polar", "heterocycle")),
    SeedRecord(
        "trimethoprim",
        "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC",
        ("antibacterial", "heterocycle"),
    ),
    SeedRecord(
        "sulfamethoxazole",
        "CC1=NO[C@H](C)C1NS(=O)(=O)C1=CC=C(N)C=C1",
        ("antibacterial", "sulfonamide"),
    ),
    SeedRecord("benzocaine", "CCOC(=O)c1ccc(N)cc1", ("oral", "aromatic")),
    SeedRecord("procainamide", "CCN(CC)CCNC(=O)c1ccc(N)cc1", ("oral", "amine")),
    SeedRecord("salicylamide", "NC(=O)c1ccccc1O", ("oral", "aromatic")),
    SeedRecord("allopurinol", "c1nc2[nH]ncc2[nH]1", ("heterocycle", "polar")),
    SeedRecord("theophylline", "Cn1c(=O)[nH]c2ncn(C)c2c1=O", ("cns", "heterocycle")),
    SeedRecord("pyridoxine_core", "CC1=NC=C(CO)C(CO)O1", ("polar", "heterocycle")),
    SeedRecord("isonipecotic_amide", "NC(=O)C1CCNCC1", ("amine", "polar")),
    SeedRecord("morpholine_benzamide", "O=C(Nc1ccccc1)N1CCOCC1", ("amine", "aromatic")),
    SeedRecord("piperazine_acetamide", "O=C(CN1CCNCC1)Nc1ccccc1", ("amine", "aromatic")),
    SeedRecord("anisamide", "COc1ccc(C(=O)N)cc1", ("oral", "aromatic")),
)

ALLOWED_ATOMIC_NUMBERS = {1, 6, 7, 8, 9, 15, 16, 17, 35}


def _stable_seed(request: GenerateRequest) -> int:
    payload = (
        f"{request.prompt or ''}|{request.qed:.4f}|{request.logp:.4f}|"
        f"{request.tpsa:.4f}|{request.mw:.4f}|{request.n}|{request.top_k}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _tokenize_prompt(prompt: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", prompt.lower()))


def _closeness(actual: float, target: float, scale: float) -> float:
    safe_scale = max(scale, 1e-6)
    return math.exp(-((actual - target) / safe_scale) ** 2)


def _lipinski_violations(mol: Chem.Mol) -> int:
    violations = 0
    if Descriptors.MolWt(mol) > 500:
        violations += 1
    if Descriptors.MolLogP(mol) > 5:
        violations += 1
    if rdMolDescriptors.CalcNumHBD(mol) > 5:
        violations += 1
    if rdMolDescriptors.CalcNumHBA(mol) > 10:
        violations += 1
    return violations


def _describe_molecule(mol: Chem.Mol) -> DescriptorBundle:
    return DescriptorBundle(
        qed=float(QED.qed(mol)),
        logp=float(Descriptors.MolLogP(mol)),
        tpsa=float(rdMolDescriptors.CalcTPSA(mol)),
        mw=float(Descriptors.MolWt(mol)),
        lipinski=_lipinski_violations(mol),
    )


@lru_cache(maxsize=None)
def _seed_descriptors(smiles: str) -> DescriptorBundle:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid seed SMILES: {smiles}")
    return _describe_molecule(mol)


@lru_cache(maxsize=None)
def _seed_fragments(smiles: str) -> tuple[str, ...]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return ()
    return tuple(sorted(BRICS.BRICSDecompose(mol, minFragmentSize=2)))


def _seed_score(seed: SeedRecord, request: GenerateRequest, prompt_tokens: set[str]) -> float:
    descriptors = _seed_descriptors(seed.smiles)
    tag_bonus = 0.18 * sum(1 for tag in seed.tags if tag in prompt_tokens)
    return (
        0.30 * _closeness(descriptors.qed, request.qed, 0.18)
        + 0.22 * _closeness(descriptors.logp, request.logp, 1.0)
        + 0.22 * _closeness(descriptors.tpsa, request.tpsa, 20.0)
        + 0.18 * _closeness(descriptors.mw, request.mw, 80.0)
        + 0.08 * (1.0 / (1 + descriptors.lipinski))
        + tag_bonus
    )


def _select_seed_records(request: GenerateRequest, limit: int = 12) -> List[SeedRecord]:
    prompt_tokens = _tokenize_prompt(request.prompt or "")
    ranked = sorted(
        SEED_LIBRARY,
        key=lambda seed: _seed_score(seed, request, prompt_tokens),
        reverse=True,
    )
    return ranked[: min(limit, len(ranked))]


def _build_fragment_pool(seeds: List[SeedRecord], rng: random.Random) -> List[Chem.Mol]:
    fragment_smiles: set[str] = set()
    for seed in seeds:
        fragment_smiles.update(_seed_fragments(seed.smiles))

    ordered = sorted(fragment_smiles)
    rng.shuffle(ordered)

    fragment_mols: List[Chem.Mol] = []
    for fragment in ordered[:40]:
        mol = Chem.MolFromSmiles(fragment)
        if mol is not None:
            fragment_mols.append(mol)
    return fragment_mols


def _passes_quality_filters(mol: Chem.Mol, descriptors: DescriptorBundle) -> bool:
    if "." in Chem.MolToSmiles(mol, canonical=True):
        return False
    if any(atom.GetAtomicNum() not in ALLOWED_ATOMIC_NUMBERS for atom in mol.GetAtoms()):
        return False
    if abs(sum(atom.GetFormalCharge() for atom in mol.GetAtoms())) > 1:
        return False
    if Descriptors.NumRadicalElectrons(mol) != 0:
        return False
    if not 150 <= descriptors.mw <= 520:
        return False
    if not -1.0 <= descriptors.logp <= 5.5:
        return False
    if not 15.0 <= descriptors.tpsa <= 150.0:
        return False
    if rdMolDescriptors.CalcNumAromaticRings(mol) > 3:
        return False
    if rdMolDescriptors.CalcNumRings(mol) > 5:
        return False
    if rdMolDescriptors.CalcNumRotatableBonds(mol) > 10:
        return False
    return True


def _prompt_bonus(prompt_tokens: set[str], descriptors: DescriptorBundle) -> float:
    bonus = 0.0
    if {"cns", "brain", "bbb"} & prompt_tokens:
        if descriptors.tpsa <= 90 and 1.0 <= descriptors.logp <= 4.0 and descriptors.mw <= 450:
            bonus += 0.05
        else:
            bonus -= 0.03
    if {"oral", "bioavailable"} & prompt_tokens:
        bonus += 0.04 if descriptors.lipinski == 0 else -0.03 * descriptors.lipinski
    if {"polar", "soluble"} & prompt_tokens and descriptors.tpsa >= 70:
        bonus += 0.03
    if {"lipophilic", "membrane"} & prompt_tokens and descriptors.logp >= 3.0:
        bonus += 0.03
    if {"fragment", "fragment-like"} & prompt_tokens:
        bonus += 0.03 if descriptors.mw <= 300 else -0.03
    return bonus


def _is_meaningful_prompt(prompt: str) -> bool:
    text = (prompt or "").strip().lower()
    if not text:
        return True

    if len(text) < 8:
        return False

    if re.search(r"(.)\1{4,}", text):
        return False

    tokens = re.findall(r"[a-z]+", text)
    if len(tokens) < 2:
        return False

    long_tokens = [token for token in tokens if len(token) >= 3]
    if len(long_tokens) < 2:
        return False

    alpha_count = sum(1 for char in text if "a" <= char <= "z")
    if alpha_count < 6:
        return False

    vowels = sum(1 for char in text if char in "aeiou")
    vowel_ratio = vowels / alpha_count if alpha_count else 0.0
    if vowel_ratio < 0.20 or vowel_ratio > 0.85:
        return False

    known_intent_words = {
        "small",
        "low",
        "oral",
        "brain",
        "cns",
        "bbb",
        "anti",
        "antiinflammatory",
        "inflammatory",
        "analgesic",
        "polar",
        "soluble",
        "lipophilic",
        "membrane",
        "fragment",
        "bioavailable",
        "drug",
        "molecule",
        "mw",
        "logp",
        "qed",
        "tpsa",
    }

    if any(token in known_intent_words for token in tokens):
        return True

    # If no explicit medicinal keywords are present, require richer natural language.
    return len(tokens) >= 4 and len(set(tokens)) >= 3


def _reward(
    descriptors: DescriptorBundle,
    request: GenerateRequest,
    prompt_tokens: set[str],
    is_novel: bool,
) -> float:
    score = (
        0.34 * _closeness(descriptors.qed, request.qed, 0.18)
        + 0.22 * _closeness(descriptors.logp, request.logp, 1.0)
        + 0.20 * _closeness(descriptors.tpsa, request.tpsa, 20.0)
        + 0.14 * _closeness(descriptors.mw, request.mw, 80.0)
        + 0.10 * (1.0 / (1 + descriptors.lipinski))
    )
    if is_novel:
        score += 0.03
    score += _prompt_bonus(prompt_tokens, descriptors)
    return float(max(score, 0.0))


def _canonicalize_candidate(mol: Chem.Mol) -> tuple[str, Chem.Mol] | None:
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        return None

    smiles = Chem.MolToSmiles(mol, canonical=True)
    if "*" in smiles or "." in smiles:
        return None
    canonical = Chem.MolFromSmiles(smiles)
    if canonical is None:
        return None
    return smiles, canonical


def _canonicalize_smiles(smiles: str) -> tuple[str, Chem.Mol] | None:
    normalized = re.sub(r"\s+", "", smiles).strip()
    if not normalized or "." in normalized:
        return None
    mol = Chem.MolFromSmiles(normalized)
    if mol is None:
        return None
    return _canonicalize_candidate(mol)


def _embed_sdf(mol: Chem.Mol, rng: random.Random) -> Optional[str]:
    try:
        mol3d = Chem.AddHs(Chem.Mol(mol))
        params = AllChem.ETKDGv3()
        params.randomSeed = rng.randint(1, 2**31 - 1)
        status = AllChem.EmbedMolecule(mol3d, params)
        if status != 0:
            status = AllChem.EmbedMolecule(mol3d, randomSeed=params.randomSeed, useRandomCoords=True)
        if status != 0:
            return None
        AllChem.UFFOptimizeMolecule(mol3d, maxIters=200)
        mol3d = Chem.RemoveHs(mol3d)
        return Chem.MolToMolBlock(mol3d) + "\n$$$$\n"
    except Exception as exc:
        logger.warning("3D generation failed: %s", exc)
        return None


@lru_cache(maxsize=1)
def _load_learned_model():
    if _learned_model_import_error is not None:
        raise RuntimeError(f"Learned model dependencies are unavailable: {_learned_model_import_error}")
    assert torch is not None and AutoTokenizer is not None and AutoModelForCausalLM is not None

    tokenizer = AutoTokenizer.from_pretrained(LEARNED_MODEL_NAME, revision=LEARNED_MODEL_REVISION)
    model = AutoModelForCausalLM.from_pretrained(LEARNED_MODEL_NAME, revision=LEARNED_MODEL_REVISION)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    return tokenizer, model, device


def _set_torch_seed(seed: int):
    assert torch is not None
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _rank_and_materialize_results(
    candidate_records: list[tuple[float, str, Chem.Mol, DescriptorBundle]],
    rng: random.Random,
    top_k: int,
) -> List[MoleculeResult]:
    candidate_records.sort(key=lambda item: item[0], reverse=True)
    top_records = candidate_records[:top_k]

    results: List[MoleculeResult] = []
    for reward_score, smiles, mol, descriptors in top_records:
        results.append(
            MoleculeResult(
                smiles=smiles,
                sdf_string=_embed_sdf(mol, rng),
                qed=descriptors.qed,
                logp=descriptors.logp,
                tpsa=descriptors.tpsa,
                mw=descriptors.mw,
                lipinski=descriptors.lipinski,
                reward_score=reward_score,
            )
        )
    return results


def _fragment_generation_run(request: GenerateRequest) -> GenerationRun:
    rng = random.Random(_stable_seed(request))
    prompt_tokens = _tokenize_prompt(request.prompt or "")
    selected_seeds = _select_seed_records(request)
    fragment_pool = _build_fragment_pool(selected_seeds, rng)
    seed_smiles = {
        Chem.MolToSmiles(Chem.MolFromSmiles(seed.smiles), canonical=True)
        for seed in selected_seeds
    }

    candidate_records: list[tuple[float, str, Chem.Mol, DescriptorBundle]] = []
    seen_smiles: set[str] = set()
    attempted_count = 0
    target_valid = max(request.n, request.top_k * 4)
    max_attempts = max(request.n * 25, 400)

    if fragment_pool:
        for candidate in BRICS.BRICSBuild(
            fragment_pool,
            onlyCompleteMols=True,
            uniquify=True,
            scrambleReagents=False,
            maxDepth=3,
        ):
            attempted_count += 1
            canonicalized = _canonicalize_candidate(candidate)
            if canonicalized is None:
                if attempted_count >= max_attempts:
                    break
                continue

            smiles, canonical_mol = canonicalized
            if smiles in seen_smiles:
                if attempted_count >= max_attempts:
                    break
                continue

            descriptors = _describe_molecule(canonical_mol)
            if not _passes_quality_filters(canonical_mol, descriptors):
                if attempted_count >= max_attempts:
                    break
                continue

            seen_smiles.add(smiles)
            candidate_records.append(
                (
                    _reward(descriptors, request, prompt_tokens, smiles not in seed_smiles),
                    smiles,
                    canonical_mol,
                    descriptors,
                )
            )

            if len(candidate_records) >= target_valid or attempted_count >= max_attempts:
                break

    if len(candidate_records) < request.top_k:
        for seed in selected_seeds:
            mol = Chem.MolFromSmiles(seed.smiles)
            if mol is None:
                continue
            smiles = Chem.MolToSmiles(mol, canonical=True)
            if smiles in seen_smiles:
                continue
            descriptors = _describe_molecule(mol)
            if not _passes_quality_filters(mol, descriptors):
                continue
            seen_smiles.add(smiles)
            candidate_records.append(
                (
                    _reward(descriptors, request, prompt_tokens, False),
                    smiles,
                    mol,
                    descriptors,
                )
            )
            if len(candidate_records) >= request.top_k:
                break

    results = _rank_and_materialize_results(candidate_records, rng, request.top_k)
    return GenerationRun(
        backend="fragment",
        model_name="BRICS fragment recombination",
        attempted_count=attempted_count,
        valid_count=len(candidate_records),
        molecules=results,
    )


def _learned_generation_run(request: GenerateRequest) -> GenerationRun:
    assert torch is not None

    rng_seed = _stable_seed(request)
    rng = random.Random(rng_seed)
    prompt_tokens = _tokenize_prompt(request.prompt or "")
    selected_seeds = _select_seed_records(request)
    seed_smiles = {
        Chem.MolToSmiles(Chem.MolFromSmiles(seed.smiles), canonical=True)
        for seed in selected_seeds
    }

    tokenizer, model, device = _load_learned_model()

    bos_token_id = tokenizer.bos_token_id
    eos_token_id = tokenizer.eos_token_id
    pad_token_id = tokenizer.pad_token_id
    if bos_token_id is None or eos_token_id is None or pad_token_id is None:
        raise RuntimeError("Learned generator tokenizer is missing BOS/EOS/PAD tokens.")

    target_valid = max(request.n, request.top_k * 4)
    max_attempts = max(request.n * 4, request.top_k * 12, 64)
    batch_size = min(LEARNED_BATCH_SIZE, max_attempts)
    max_new_tokens = min(LEARNED_MAX_NEW_TOKENS, int(getattr(model.config, "n_positions", 128)) - 1)

    candidate_records: list[tuple[float, str, Chem.Mol, DescriptorBundle]] = []
    seen_smiles: set[str] = set()
    attempted_count = 0
    _set_torch_seed(rng_seed)

    while attempted_count < max_attempts and len(candidate_records) < target_valid:
        current_batch = min(batch_size, max_attempts - attempted_count)
        input_ids = torch.full((current_batch, 1), bos_token_id, dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_ids)
        _set_torch_seed(rng_seed + attempted_count)

        with torch.no_grad():
            outputs = model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                do_sample=True,
                top_p=0.96,
                temperature=0.95,
                repetition_penalty=1.05,
                max_new_tokens=max_new_tokens,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
            )

        generated_texts = tokenizer.batch_decode(outputs, skip_special_tokens=True)
        for generated in generated_texts:
            attempted_count += 1
            canonicalized = _canonicalize_smiles(generated)
            if canonicalized is None:
                continue

            smiles, mol = canonicalized
            if smiles in seen_smiles:
                continue

            descriptors = _describe_molecule(mol)
            if not _passes_quality_filters(mol, descriptors):
                continue

            seen_smiles.add(smiles)
            candidate_records.append(
                (
                    _reward(descriptors, request, prompt_tokens, smiles not in seed_smiles),
                    smiles,
                    mol,
                    descriptors,
                )
            )

            if len(candidate_records) >= target_valid:
                break

    results = _rank_and_materialize_results(candidate_records, rng, request.top_k)
    return GenerationRun(
        backend="learned",
        model_name=LEARNED_MODEL_NAME,
        attempted_count=attempted_count,
        valid_count=len(candidate_records),
        molecules=results,
    )


def _merge_runs(primary: GenerationRun, secondary: GenerationRun, request: GenerateRequest) -> GenerationRun:
    merged: dict[str, MoleculeResult] = {}
    for run in (primary, secondary):
        for molecule in run.molecules:
            existing = merged.get(molecule.smiles)
            if existing is None or molecule.reward_score > existing.reward_score:
                merged[molecule.smiles] = molecule

    ranked = sorted(merged.values(), key=lambda molecule: molecule.reward_score, reverse=True)
    return GenerationRun(
        backend=f"{primary.backend}+{secondary.backend}",
        model_name=primary.model_name or secondary.model_name,
        attempted_count=primary.attempted_count + secondary.attempted_count,
        valid_count=primary.valid_count + secondary.valid_count,
        molecules=ranked[: request.top_k],
    )


def call_generation_model(request: GenerateRequest) -> GenerationRun:
    backend = DEFAULT_GENERATOR_BACKEND
    if backend == "fragment":
        return _fragment_generation_run(request)

    if backend != "learned":
        logger.warning("GENERATOR_BACKEND=%s is unsupported; using fragment backend.", backend)
        return _fragment_generation_run(request)

    try:
        return _learned_generation_run(request)
    except Exception as exc:
        logger.exception("Learned model generation failed: %s", exc)
        logger.warning("Falling back to fragment backend after learned generation failure.")
        return _fragment_generation_run(request)


@app.get("/")
def read_root():
    active_backend = DEFAULT_GENERATOR_BACKEND if DEFAULT_GENERATOR_BACKEND in {"learned", "fragment"} else "fragment"
    active_model = LEARNED_MODEL_NAME if active_backend == "learned" else "BRICS fragment recombination"
    return {
        "status": "ok",
        "message": "MolGen backend is running",
        "generator_backend": active_backend,
        "generator_model": active_model,
    }


@app.post("/generate")
def generate(request: GenerateRequest) -> GenerateResponse:
    if not _is_meaningful_prompt(request.prompt or ""):
        raise HTTPException(
            status_code=422,
            detail=(
                "Prompt looks invalid or gibberish. Please describe your molecular goal "
                "using meaningful words, for example: 'small oral anti-inflammatory "
                "analgesic with low molecular weight'."
            ),
        )

    generation = call_generation_model(request)
    validity_pct = 0.0
    if generation.attempted_count:
        validity_pct = generation.valid_count / generation.attempted_count * 100

    _store_generation_record(request, generation, validity_pct)

    return GenerateResponse(
        prompt=request.prompt or "",
        generator_backend=generation.backend,
        generator_model=generation.model_name,
        attempted_count=generation.attempted_count,
        valid_count=generation.valid_count,
        returned_count=len(generation.molecules),
        validity_pct=validity_pct,
        molecules=generation.molecules,
    )

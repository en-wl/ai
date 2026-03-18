from __future__ import annotations

from dataclasses import dataclass
import fracs
from fracs import frac, Frac, div
from typing import Iterable, NamedTuple, Optional, Tuple

Size = int
Borderline = Optional[Size]  # opposite adjacent size, or None

S_60 = 0
S_70 = 1
S_80 = 2
S_99 = 3

SIZE_IDX = {60: 0, 70: 1, 80: 2, 99: 3}
IDX_TO_SIZE = (60, 70, 80, 99)

class ModelSizeScore(NamedTuple):
    """Result from model_size_score aggregation."""
    size: Size
    lower: fracs.Rational   # fraction of mass strictly below chosen size
    higher: fracs.Rational  # fraction of mass strictly above chosen size
    mass: Tuple[fracs.Rational, fracs.Rational, fracs.Rational, fracs.Rational]  # [S_60, S_70, S_80, S_99]

    def mass_lower(self, size_idx):
        return sum(self.mass[0:size_idx])

    def mass_higher(self, size_idx):
        return sum(self.mass[size_idx+1:])

def model_size_score(rows: Iterable[Tuple[int, Size, Borderline]]) -> ModelSizeScore:
    """
    Reduce multiple runs for a model for a gid into:
      - size: {60,70,80,99} via weighted upper-median (cumulative >= half from top)
      - higher: fraction of mass strictly above chosen size
      - lower: fraction of mass strictly below chosen size

    Input rows: iterable of (count, size, borderline)
      - size is the "winning" side
      - borderline is the opposite adjacent size (e.g. size=60, borderline=70) or None
      - all inputs are assumed valid
    """
    winner_share = frac('2/3')
    loser_share = 1 - winner_share

    mass = [0, 0, 0, 0]  # [S_60, S_70, S_80, S_99]
    total = 0

    for cnt, size, borderline in rows:
        c = frac(cnt)
        total += c
        if borderline is None:
            mass[SIZE_IDX[size]] += c
        else:
            mass[SIZE_IDX[size]] += winner_share * c
            mass[SIZE_IDX[borderline]] += loser_share * c
    if total == 0:
        raise ValueError

    for i in range(4):
        mass[i] = frac(mass[i], total)

    # Weighted upper-median on ordered sizes (99 > 80 > 70 > 60)
    cumulative = 0
    chosen = None
    for idx in reversed(range(4)):
        cumulative += mass[idx]
        if cumulative >= frac('1/2'):
            chosen = idx
            break
    if chosen is None:
        raise ValueError

    # Compute higher and lower fractions
    higher = cumulative - mass[chosen]
    lower = 1 - cumulative

    return ModelSizeScore(IDX_TO_SIZE[chosen], lower, higher, tuple(mass))


ModelOutputs = dict[str, ModelSizeScore]

# Expected model keys (you can pass fewer; missing models just contribute no evidence)
M_GPT52 = "gpt-5.2"
M_DEEPSEEK = "deepseek-v3.2"
M_OSS = "gpt-oss-120b"
M_QWEN = "qwen3-235b-a22b"
M_GEMINI = "gemini-2.5-flash"
M_LLAMA = "llama-3.3-70b"

WEIGHTS_60 = {
    M_GPT52: 1,
    M_DEEPSEEK: 1,
    M_OSS: frac('0.7'),
    M_QWEN: frac('0.7'),
    M_GEMINI: frac('0.3'),
}
WEIGHT_60_LLAMA = frac('0.6') # not always included
TOTAL_60 = sum(WEIGHTS_60.values())
THRESHOLD_60 = frac('0.6')
#THRESHOLD_60 = div(frac('2.2'),TOTAL_60)

WEIGHTS_70 = {
    M_OSS: 1,
    M_GPT52: frac('0.9'),
    M_DEEPSEEK: frac('0.9'),
    M_QWEN: frac('0.7'),
    #M_GEMINI: frac('0.3'),
}
TOTAL_70 = sum(WEIGHTS_70.values())
THRESHOLD_70 = frac('0.6')
#THRESHOLD_70 = div(frac('2.6'),TOTAL_70)

@dataclass
class EnsembleScores:
    """Computed scores and signals from all models."""

    # Raw model outputs for reference/debugging
    raw_outputs: ModelOutputs

    # Stage 1: Exclusion signals
    gpt52_excl_direct: bool = False
    deepseek_excl_corroborated: bool = False

    # Stage 2: Size 60 signals
    has_60_veto: bool = False
    size_60_score: fracs.Rational = 0

    # Stage 3: 70 vs 80 signals
    size_70_score: fracs.Rational = 0

def compute_ensemble_scores(outputs: ModelOutputs) -> EnsembleScores:
    """Pure calculation: compute all scores and signals from model outputs."""

    scores = EnsembleScores(raw_outputs=outputs)

    # Extract all model outputs upfront
    gpt52 = outputs.get(M_GPT52)
    deepseek = outputs.get(M_DEEPSEEK)
    oss = outputs.get(M_OSS)
    qwen = outputs.get(M_QWEN)
    gemini = outputs.get(M_GEMINI)
    llama = outputs.get(M_LLAMA)

    # ========================================
    # Stage 1: Exclusion signals
    # ========================================

    if gpt52 and gpt52.mass[S_99] >= frac('2/3'):
        scores.gpt52_excl_direct = True

    if deepseek and deepseek.mass[S_99] >= frac('4/5'):
        corroborators = 0

        if qwen and qwen.mass[S_99] >= frac('4/5'):
            corroborators += 1

        if gemini and gemini.mass[S_99] >= frac('4/5'):
            corroborators += 1

        if oss and oss.mass[S_99] >= frac('4/5'):
            corroborators += 1

        if corroborators >= 1:
            scores.deepseek_excl_corroborated = True

    # ========================================
    # Stage 2: Size 60 signals
    # ========================================

    if gpt52: # and deepseek:
        scores.has_60_veto = gpt52.mass[S_60] == 0
                             # or gpt52.mass[S_70] <= frac('0.2')
                             # or (deepseek.mass[S_60] == 0 and deepseek.mass[S_70] <= frac('0.2')))
    else:
        # we have no data from gpt52 or deepseek, so play it safe
        scores.has_60_veto = True
        
    score = 0
    for model, weight in WEIGHTS_60.items():
        try:
            output = outputs[model]
        except KeyError:
            continue
        score += weight * output.mass[S_60]
        score -= weight * output.mass_higher(S_70)
    scores.size_60_score = div(score, TOTAL_60)
        
    if llama and scores.size_60_score < THRESHOLD_60 and llama.mass[S_60] >= frac('0.8'):
        score += WEIGHT_60_LLAMA * llama.mass[S_60]
        scores.size_60_score = div(score, TOTAL_60 + WEIGHT_60_LLAMA)

    # ========================================
    # Stage 3: 70 vs 80 signals
    # ========================================

    score = 0
    for model, weight in WEIGHTS_70.items():
        try:
            output = outputs[model]
        except KeyError:
            continue
        mass = output.mass[S_60] + output.mass[S_70]
        if model == M_DEEPSEEK:
            mass += output.mass[S_80] * frac('0.3') # deepseek 80 often acts like conservative 70
        score += weight * mass
    scores.size_70_score = div(score, TOTAL_70)

    # =======================================

    return scores
    

class SizeReason(NamedTuple):
    size: int
    excl: str
    veto_60: bool
    score_60: fracs.Rational
    score_70: fracs.Rational
    def __str__(self):
        if self.size == 99:
            return self.excl
        
        if self.size == 60:
            return f"{100*self.score_60:.0f}/{100*THRESHOLD_60:.0f}"
        elif self.veto_60:
            sz_60_reason = f"veto 60 {100*self.score_60:.0f}/{100*THRESHOLD_60:.0f}"
        else:
            sz_60_reason = f"not 60 {100*self.score_60:.0f}/{100*THRESHOLD_60:.0f}"

        return f"{100*self.score_70:.0f}/{100*THRESHOLD_70:.0f} ({sz_60_reason})"

def determine_final_size(outputs: ModelOutputs) -> Size:
    """
    Determine a final size in {60,70,80,99} using per-model inputs.
    """
    scores = compute_ensemble_scores(outputs)
    excl = ""

    if scores.gpt52_excl_direct:
        sz = 99
        excl = "gpt52"
    elif scores.deepseek_excl_corroborated:
        sz = 99
        excl = "deepseek+"
    elif not scores.has_60_veto and scores.size_60_score >= THRESHOLD_60:
        sz = 60
    elif scores.size_70_score >= THRESHOLD_70:
        sz = 70
    else:
        sz = 80

    veto_60 = sz > 60 and scores.size_60_score >= THRESHOLD_60

    return (sz, SizeReason(sz, excl, veto_60, scores.size_60_score, scores.size_70_score))

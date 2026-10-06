"""Interface LLM agnostique au backend.

Tout code specifique a un fournisseur (Gemini, OpenAI-compatible, local...) vit
dans son propre module et traduit vers/depuis ces types normalises. Le reste du
harnais (boucle agent, metriques, bench) ne depend QUE de ce fichier, donc les
changements d'API cote fournisseur restent confines a un seul module.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable


# --- Schema des outils exposes au modele --------------------------------------

@dataclass
class ToolSpec:
    """Declaration d'un outil (JSON Schema des parametres), backend-agnostique."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema: {"type":"object","properties":{...},"required":[...]}


# --- Messages (transcript normalise) ------------------------------------------

@dataclass
class ToolCall:
    """Un appel d'outil demande par le modele."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """Un element du transcript. role ∈ {system,user,assistant,tool}."""
    role: str
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # pour role == "tool": a quel appel on repond
    tool_call_id: str | None = None
    tool_name: str | None = None


# --- Usage normalise ----------------------------------------------------------

@dataclass
class Usage:
    """Comptage de tokens normalise entre fournisseurs.

    Chaque backend remplit ce qu'il peut; les champs absents restent a 0.
    `raw` garde la structure brute du fournisseur pour l'analyse fine.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0      # tokens d'input servis depuis un cache
    thinking_tokens: int = 0    # tokens de raisonnement (si exposes)
    total_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class LLMResponse:
    """Resultat d'un pas de modele."""
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    latency_ms: float = 0.0
    model: str = ""
    raw: Any = None


# --- Contrat du client --------------------------------------------------------

class LLMClient(abc.ABC):
    """Un backend LLM. `step` prend l'etat courant et renvoie le pas suivant."""

    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    def step(
        self,
        system: str,
        history: list[Message],
        tools: list[ToolSpec],
    ) -> LLMResponse:
        """Un aller-retour modele: renvoie du texte et/ou des appels d'outils + usage."""
        raise NotImplementedError

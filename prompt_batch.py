"""Turn character blocks, plate prompts, and seed lines into one shot per image.

Each shot is a finished prompt and an integer seed. Prompts use PlatePress
plate ids: a line such as p01 or p01_station starts the next image, and blank
lines inside that plate stay in the prompt. A later version can hang reference
images on the same shot. This version does not read images. Character
descriptions are plain text, so a token written inside a description is not
expanded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ComfyUI seed sockets use this range. The node does not load a model.
SEED_MAX = 0xFFFFFFFFFFFFFFFF

# A token is CHAR plus a positive integer. CHAR10 is one token, not CHAR1.
# The lookbehind keeps CHAR100 intact when only CHAR1 or CHAR10 is defined.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])CHAR[1-9]\d*")
# CHAR1 on its own line, or CHAR1 followed by the description on that same line.
CHAR_HEADER_RE = re.compile(r"^(CHAR[1-9]\d*)(?:\s+(\S.*))?$")
# p01, p001, p09A, p01_station, p09A_morning. Same plate ids as PlatePress.
PLATE_HEADER_RE = re.compile(
    r"^(?P<id>[Pp]\d+[A-Za-z]?(?:_[A-Za-z0-9_]+)?)(?:\s+(?P<rest>\S.*))?$"
)


class PromptBatchError(ValueError):
    """Text the node can show in ComfyUI without a traceback."""


@dataclass(frozen=True)
class Shot:
    prompt: str
    seed: int
    plate_id: str
    # Tokens that were replaced in this prompt, in the order they appear.
    # Unused by the node outputs. The next version uses this to attach each
    # character's reference images to the shots that name that character.
    character_tokens: tuple[str, ...]


def build_batch(characters: str, prompts: str, seeds: str, roll_seed, prefix: str = "") -> list[Shot]:
    """Parse the boxes. roll_seed() returns one new seed."""
    character_map = _parse_characters(_as_text(characters, "Characters"))
    prefix_text, prefix_tokens = _apply_characters(
        _as_text(prefix, "Prefix").strip(),
        character_map,
    )
    plates = _split_prompts(_as_text(prompts, "Prompts"))
    seed_values = _parse_seeds(_as_text(seeds, "Seeds"), len(plates), roll_seed)
    shots = []
    for (plate_id, prompt), seed in zip(plates, seed_values):
        finished, tokens = _apply_characters(prompt, character_map)
        if prefix_text:
            finished = f"{prefix_text}\n{finished}"
        shots.append(
            Shot(
                prompt=finished,
                seed=seed,
                plate_id=plate_id,
                character_tokens=_merge_tokens(prefix_tokens, tokens),
            )
        )
    return shots


def seeds_are_rolled(seeds: str) -> bool:
    """True when at least one seed is chosen at queue time.

    An empty Seeds box chooses a seed for every prompt. A blank line chooses
    one seed. Explicit integers stay cached between queues.
    """
    text = _as_text(seeds, "Seeds")
    if text.strip() == "":
        return True
    return any(line.strip() == "" for line in text.splitlines())


def _as_text(value, box_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PromptBatchError(f"{box_name} must be text.")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _plate_key(plate_id: str) -> str:
    """p1_station and p001_station are the same plate. p01 and p01_station are not."""
    match = re.fullmatch(r"[Pp](\d+)([A-Za-z])?(?:_([A-Za-z0-9_]+))?", plate_id)
    if match is None:
        return plate_id.lower()
    letter = (match.group(2) or "").lower()
    rest = (match.group(3) or "").lower()
    core = f"p{int(match.group(1)):03d}{letter}"
    return f"{core}_{rest}" if rest else core


def _split_prompts(text: str) -> list[tuple[str, str]]:
    """Return (plate id, body) in wall order. The id is not part of the body."""
    if text.strip() == "":
        raise PromptBatchError(
            "Prompts is empty. Start each prompt with a plate id on its own line, such as p01 or p01_station."
        )
    plates: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    current_id: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current_id, buf
        if current_id is None:
            buf = []
            return
        while buf and buf[0].strip() == "":
            buf.pop(0)
        while buf and buf[-1].strip() == "":
            buf.pop()
        body = "\n".join(buf)
        if body.strip() == "":
            raise PromptBatchError(f"{current_id} has no prompt text.")
        plates.append((current_id, body))
        current_id = None
        buf = []

    for line in text.split("\n"):
        match = PLATE_HEADER_RE.match(line.strip())
        if match is not None:
            flush()
            plate_id = match.group("id")
            key = _plate_key(plate_id)
            if key in seen:
                raise PromptBatchError(f"{plate_id} is the same plate as {seen[key]}.")
            seen[key] = plate_id
            current_id = plate_id
            rest = (match.group("rest") or "").strip()
            if rest:
                buf.append(rest)
            continue
        if current_id is None:
            if line.strip():
                raise PromptBatchError(
                    "Prompts has text before the first plate id. "
                    "Start with a line like p01 or p01_station."
                )
            continue
        buf.append(line)
    flush()
    return plates


def _split_blocks(text: str) -> list[str]:
    blocks = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _parse_characters(text: str) -> dict[str, str]:
    if text.strip() == "":
        return {}
    characters: dict[str, str] = {}
    for index, block in enumerate(_split_blocks(text), start=1):
        lines = block.split("\n")
        header = CHAR_HEADER_RE.match(lines[0].strip())
        if header is None:
            raise PromptBatchError(
                f"Characters block {index} starts with {lines[0].strip()!r}. "
                "Start the block with CHAR and a positive integer, such as CHAR1 or CHAR10. "
                "The description can follow on that same line."
            )
        token = header.group(1)
        description = re.sub(
            r"\s+",
            " ",
            "\n".join([header.group(2) or "", *lines[1:]]),
        ).strip()
        if description == "":
            raise PromptBatchError(f"{token} has no description under the token line.")
        if token in characters:
            raise PromptBatchError(f"{token} is defined more than once.")
        characters[token] = description
    return characters


def _merge_tokens(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for token in (*first, *second):
        if token not in merged:
            merged.append(token)
    return tuple(merged)


def _apply_characters(prompt: str, characters: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    if not characters:
        return prompt, ()
    used: list[str] = []

    def replace(match: re.Match) -> str:
        token = match.group(0)
        description = characters.get(token)
        if description is None:
            return token
        if token not in used:
            used.append(token)
        return description

    return TOKEN_RE.sub(replace, prompt), tuple(used)


def _parse_seeds(text: str, count: int, roll_seed) -> list[int]:
    if text.strip() == "":
        return [_rolled_seed(roll_seed) for _ in range(count)]
    # splitlines() drops a trailing newline, so the last Enter in the box
    # does not add an extra seed. A blank line in the middle still counts.
    lines = text.splitlines()
    if len(lines) != count:
        seed_word = "line" if len(lines) == 1 else "lines"
        prompt_word = "prompt" if count == 1 else "prompts"
        raise PromptBatchError(
            f"Seeds has {len(lines)} {seed_word} and Prompts has {count} {prompt_word}. "
            "Use one seed line per plate, in the same order, or leave Seeds empty."
        )
    values = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == "":
            values.append(_rolled_seed(roll_seed))
            continue
        if re.fullmatch(r"\d+", stripped) is None:
            raise PromptBatchError(
                f"Seed line {index} is {stripped!r}. "
                f"Each line must be an integer from 0 to {SEED_MAX}, or empty to choose a seed."
            )
        value = int(stripped)
        if value > SEED_MAX:
            raise PromptBatchError(
                f"Seed line {index} is {value}. The largest seed is {SEED_MAX}."
            )
        values.append(value)
    return values


def _rolled_seed(roll_seed) -> int:
    value = roll_seed()
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromptBatchError("The seed picker returned a value that is not an integer.")
    if value < 0 or value > SEED_MAX:
        raise PromptBatchError(f"The seed picker returned {value}, outside 0 to {SEED_MAX}.")
    return value

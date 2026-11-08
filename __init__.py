"""Prompt Batch custom node for ComfyUI.

Copy this folder to ComfyUI/custom_nodes/ and restart ComfyUI.
"""

from __future__ import annotations

import random

from typing_extensions import override

from comfy_api.latest import ComfyExtension, io

from .prompt_batch import SEED_MAX, _split_prompts, build_batch, seeds_are_rolled


class PromptBatch(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PromptBatch",
            display_name="Multy_prompts",
            category="utilities/prompt",
            description=(
                "Build one finished prompt, one seed, and one plate name per image. "
                "A prefix is pasted in front of every plate. "
                "Connect prompts to Start Loop (List mode). "
                "Connect seeds and plate_name to Get Item From List with index from iteration_index."
            ),
            search_aliases=[
                "Multyprompts",
                "Multy prompts",
                "Multy_prompts",
                "Prompt Batch",
                "multi prompt",
                "characters",
                "prompt list",
                "seed list",
                "plate name",
            ],
            inputs=[
                io.String.Input(
                    "characters",
                    display_name="Characters",
                    multiline=True,
                    default="",
                    dynamic_prompts=False,
                    placeholder="CHAR1\nA woman in her thirties with short black hair.\n\nCHAR2\nA tall man with a scar on his left cheek.",
                    tooltip=(
                        "Optional. One character per block, blank line between blocks. "
                        "The block starts with the token (CHAR1, CHAR2, CHAR10). "
                        "The description can follow on that same line, or on the lines under it. "
                        "It is pasted in place of the token, so write a phrase. "
                        "An empty box leaves the prompts unchanged."
                    ),
                ),
                io.String.Input(
                    "prompts",
                    display_name="Prompts",
                    multiline=True,
                    default="",
                    dynamic_prompts=False,
                    placeholder="p01\nCHAR1 stands in the rain outside a station.\n\np02\nCHAR1 hands CHAR2 a letter in a dark hallway.",
                    tooltip=(
                        "One image per plate. A line like p01, p01_station, or p04_ starts the next prompt. "
                        "Blank lines inside a plate stay in the text. The plate id is not sent to the sampler. "
                        "The same id is on the plate_name output. "
                        "CHAR tokens are replaced with that character's description."
                    ),
                ),
                io.String.Input(
                    "seeds",
                    display_name="Seeds",
                    multiline=True,
                    default="",
                    dynamic_prompts=False,
                    placeholder="657539441289641\n\n1001",
                    tooltip=(
                        "One line per plate, in the same order as p01, p02, and so on. "
                        "An integer keeps that seed. An empty line chooses a seed when you queue. "
                        "An empty box chooses a seed for every prompt. "
                        "Fewer lines than plates keep the ones you wrote and choose the rest. "
                        "On the sampler, set the seed control to fixed so its widget does not replace this seed."
                    ),
                ),
                io.String.Input(
                    "prefix",
                    display_name="Prefix",
                    multiline=True,
                    default="",
                    dynamic_prompts=False,
                    placeholder="35mm photo, natural light, fine grain",
                    tooltip=(
                        "Optional. Pasted in front of every plate, before that plate's own text. "
                        "Use it for a style line, LoRA triggers, or any text that stays the same. "
                        "An empty box adds nothing. CHAR tokens here are replaced too."
                    ),
                ),
            ],
            outputs=[
                io.String.Output(
                    id="prompts",
                    display_name="prompts",
                    is_output_list=True,
                    tooltip="One finished prompt per image. Connect to Start Loop, mode List.",
                ),
                io.Int.Output(
                    id="seeds",
                    display_name="seeds",
                    is_output_list=True,
                    tooltip=(
                        "One integer seed per prompt. "
                        "Connect to Get Item From List. Set its index from Start Loop iteration_index, "
                        "then connect the item to the sampler seed."
                    ),
                ),
                io.String.Output(
                    id="plate_name",
                    display_name="plate_name",
                    is_output_list=True,
                    tooltip=(
                        "One plate name per image, in the same order as the prompts. "
                        "p04_ comes out as p04. p02_letter comes out as p02_letter. "
                        "Connect to Get Item From List with index from iteration_index. "
                        "That item is the file name for Save Image."
                    ),
                ),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, characters, prompts, seeds, prefix):
        # Chosen seeds are new at queue time, so that queue must not reuse
        # the previous list. A full list of explicit seeds stays cached.
        try:
            prompt_count = len(_split_prompts(prompts if isinstance(prompts, str) else ""))
        except Exception:
            prompt_count = None
        if seeds_are_rolled(seeds, prompt_count):
            return float("nan")
        return False

    @classmethod
    def execute(cls, characters, prompts, seeds, prefix) -> io.NodeOutput:
        shots = build_batch(
            characters,
            prompts,
            seeds,
            lambda: random.randrange(0, SEED_MAX + 1),
            prefix,
        )
        return io.NodeOutput(
            [shot.prompt for shot in shots],
            [shot.seed for shot in shots],
            [shot.plate_id for shot in shots],
        )


class PromptBatchExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [PromptBatch]


async def comfy_entrypoint() -> PromptBatchExtension:
    return PromptBatchExtension()

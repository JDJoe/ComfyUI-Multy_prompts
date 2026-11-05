import unittest

from prompt_batch import PromptBatchError, SEED_MAX, build_batch, seeds_are_rolled


CHARACTERS = """
CHAR1
A woman in her thirties with short black hair and a grey coat.

CHAR2
A tall man with a scar on his left cheek.
"""

PROMPTS = """
p01
CHAR1 stands in the rain outside a station.

p02
CHAR1 hands CHAR2 a letter in a dark hallway.
"""


def batch(characters, prompts, seeds, rolls=(), prefix=""):
    pending = iter(rolls)

    def roll():
        return next(pending)

    return build_batch(characters, prompts, seeds, roll, prefix)


class BuildBatchTests(unittest.TestCase):
    def test_example_from_the_spec(self):
        shots = batch(CHARACTERS, PROMPTS, "657539441289641\n\n", rolls=[42])
        self.assertEqual(
            [shot.prompt for shot in shots],
            [
                "A woman in her thirties with short black hair and a grey coat. stands in the rain outside a station.",
                "A woman in her thirties with short black hair and a grey coat. hands A tall man with a scar on his left cheek. a letter in a dark hallway.",
            ],
        )
        self.assertEqual([shot.seed for shot in shots], [657539441289641, 42])
        self.assertEqual(shots[0].character_tokens, ("CHAR1",))
        self.assertEqual(shots[1].character_tokens, ("CHAR1", "CHAR2"))
        self.assertEqual([shot.plate_id for shot in shots], ["p01", "p02"])

    def test_empty_characters_leave_prompts_unchanged(self):
        shots = batch("", "p01\nA red door.\n\np02\nA blue door.", "1\n2")
        self.assertEqual([shot.prompt for shot in shots], ["A red door.", "A blue door."])
        self.assertEqual(shots[0].character_tokens, ())

    def test_prompt_that_names_nobody_is_not_rewritten(self):
        shots = batch(CHARACTERS, "p01\nAn empty platform.", "7")
        self.assertEqual(shots[0].prompt, "An empty platform.")
        self.assertEqual(shots[0].character_tokens, ())

    def test_unknown_token_stays(self):
        shots = batch(CHARACTERS, "p01\nCHAR3 waits.", "7")
        self.assertEqual(shots[0].prompt, "CHAR3 waits.")
        self.assertEqual(shots[0].character_tokens, ())

    def test_longest_token_wins(self):
        characters = "CHAR1\nred coat\n\nCHAR10\nblue coat"
        shots = batch(characters, "p01\nCHAR10 meets CHAR1.\n\np02\nCHAR100 waves.", "1\n2")
        self.assertEqual(shots[0].prompt, "blue coat meets red coat.")
        self.assertEqual(shots[0].character_tokens, ("CHAR10", "CHAR1"))
        self.assertEqual(shots[1].prompt, "CHAR100 waves.")

    def test_description_can_share_the_token_line(self):
        shots = batch("CHAR1 blaa blaa blaa", "p01\nCHAR1 waits.", "1")
        self.assertEqual(shots[0].prompt, "blaa blaa blaa waits.")

    def test_description_is_one_phrase_and_is_not_expanded(self):
        characters = "CHAR1\nshort black hair\nand a grey coat, friend of CHAR2\n\nCHAR2\nscarred man"
        shots = batch(characters, "p01\nCHAR1.", "1")
        self.assertEqual(shots[0].prompt, "short black hair and a grey coat, friend of CHAR2.")
        self.assertEqual(shots[0].character_tokens, ("CHAR1",))

    def test_blank_lines_inside_a_plate_stay(self):
        shots = batch("", "p01\nline one\n\nline two\n\np02_letter\nstill one plate", "3\n4")
        self.assertEqual(shots[0].prompt, "line one\n\nline two")
        self.assertEqual(shots[1].prompt, "still one plate")
        self.assertEqual(shots[1].plate_id, "p02_letter")

    def test_text_on_the_header_line_is_the_prompt(self):
        shots = batch("", "p01 CHAR1 stands in the rain.\n\np1_station\nsecond", "1\n2")
        self.assertEqual(shots[0].prompt, "CHAR1 stands in the rain.")
        self.assertEqual(shots[1].plate_id, "p1_station")

    def test_p1_and_p001_are_the_same_plate(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "p1\nfirst\n\np001\nsecond", "1\n2")
        self.assertIn("same plate", str(caught.exception))

    def test_text_before_the_first_plate_is_an_error(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "CHAR1 stands here.\n\np01\nmore", "1")
        self.assertIn("before the first plate id", str(caught.exception))

    def test_empty_plate_body(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "p01\n\np02\nhello", "1\n2")
        self.assertIn("p01 has no prompt text", str(caught.exception))

    def test_empty_seed_box_rolls_one_seed_per_prompt(self):
        shots = batch("", "p01\none\n\np02\ntwo\n\np03\nthree", "", rolls=[4, 5, 6])
        self.assertEqual([shot.seed for shot in shots], [4, 5, 6])

    def test_blank_seed_line_rolls_and_trailing_newline_does_not_add_a_line(self):
        shots = batch("", "p01\none\n\np02\ntwo", "8\n\n", rolls=[9])
        self.assertEqual([shot.seed for shot in shots], [8, 9])

    def test_seed_count_must_match(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "p01\none\n\np02\ntwo", "1")
        self.assertIn("Seeds has 1 line", str(caught.exception))
        self.assertIn("Prompts has 2 prompts", str(caught.exception))

    def test_bad_seed(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "p01\none", "nope")
        self.assertIn("Seed line 1", str(caught.exception))

    def test_seed_above_ksampler_max(self):
        with self.assertRaises(PromptBatchError):
            batch("", "p01\none", str(SEED_MAX + 1))

    def test_empty_prompts(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("", "\n\n", "")
        self.assertIn("Prompts is empty", str(caught.exception))

    def test_bad_character_token(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("Hero\ntall", "Hero walks.", "1")
        self.assertIn("Characters block 1", str(caught.exception))

    def test_char_zero_is_rejected(self):
        with self.assertRaises(PromptBatchError):
            batch("CHAR0\nnobody", "CHAR0.", "1")

    def test_duplicate_character(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("CHAR1\nred\n\nCHAR1\nblue", "CHAR1.", "1")
        self.assertIn("defined more than once", str(caught.exception))

    def test_character_without_description(self):
        with self.assertRaises(PromptBatchError) as caught:
            batch("CHAR1\n", "CHAR1.", "1")
        self.assertIn("no description", str(caught.exception))

    def test_prefix_is_pasted_in_front_of_every_plate(self):
        shots = batch(
            CHARACTERS,
            PROMPTS,
            "1\n2",
            prefix="35mm photo, natural light\nCHAR1 in frame",
        )
        self.assertTrue(shots[0].prompt.startswith("35mm photo, natural light\n"))
        self.assertIn("stands in the rain", shots[0].prompt)
        self.assertIn("short black hair", shots[0].prompt)
        self.assertTrue(shots[1].prompt.startswith("35mm photo, natural light\n"))
        self.assertIn("CHAR1", shots[0].character_tokens)
        self.assertNotIn("p01", shots[0].prompt)

    def test_empty_prefix_adds_nothing(self):
        shots = batch("", "p01\nA red door.", "1", prefix="  \n")
        self.assertEqual(shots[0].prompt, "A red door.")

    def test_seeds_are_rolled_only_for_blank_lines(self):
        self.assertTrue(seeds_are_rolled(""))
        self.assertTrue(seeds_are_rolled("1\n\n2"))
        self.assertFalse(seeds_are_rolled("1\n2\n"))
        self.assertFalse(seeds_are_rolled("0"))


if __name__ == "__main__":
    unittest.main()

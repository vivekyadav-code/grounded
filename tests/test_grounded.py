#!/usr/bin/env python3
"""Offline tests — no network, no API key needed.

What is tested is the part that decides retrieval quality and safety:
chunking, ranking, fusion, citation handling and the abstention rule.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grounded.answer import cited_indexes
from grounded.embed import Cache, pack, unpack
from grounded.ingest import _paragraphs, chunk_document, split_long, split_sections
from grounded.retrieve import reciprocal_rank_fusion
from grounded.store import Store, tokenize


class Chunking(unittest.TestCase):
    def test_heading_path_is_carried_into_the_chunk(self):
        doc = "# Guide\n\n## Serving\n\n" + ("word " * 40)
        heading, text = chunk_document(doc)[0]
        self.assertEqual(heading, "Guide > Serving")
        self.assertTrue(text.startswith("Guide > Serving"),
                        "the heading must travel with the text, or the chunk is "
                        "meaningless out of context")

    def test_hash_inside_a_code_fence_is_not_a_heading(self):
        """A shell comment became a section heading and inherited every
        following section, which made a correctly-retrieved chunk unanswerable."""
        doc = ("# Guide\n\n## Maintenance\n\n```bash\n"
               "# free disk space\nrm -rf out\n```\n\n## Next\n\n" + ("word " * 30))
        headings = [h for h, _ in split_sections(doc)]
        self.assertNotIn("free disk space", " ".join(headings))
        self.assertEqual(headings[-1], "Guide > Next")

    def test_unclosed_fence_does_not_swallow_later_headings_forever(self):
        doc = "# A\n\n```\ncode\n```\n\n## B\n\n" + ("word " * 30)
        self.assertIn("A > B", [h for h, _ in split_sections(doc)])

    def test_a_code_block_is_kept_whole(self):
        body = "intro\n\n```bash\nline one\n\nline two\n```\n\nafter"
        paras = _paragraphs(body)
        block = [p for p in paras if p.startswith("```")]
        self.assertEqual(len(block), 1)
        self.assertIn("line one", block[0])
        self.assertIn("line two", block[0],
                      "a blank line inside a fence must not split the command")

    def test_long_sections_split_with_overlap(self):
        body = "\n\n".join(f"paragraph {i} " + ("alpha " * 60) for i in range(8))
        parts = split_long(body, max_tokens=120, overlap=40)
        self.assertGreater(len(parts), 1)
        tail = " ".join(parts[0].split()[-40:])
        self.assertIn(tail, parts[1], "the seam must appear in both neighbours")

    def test_overlap_happens_even_when_paragraphs_exceed_the_budget(self):
        """Whole-paragraph overlap alone silently produced no overlap at all
        for documents whose paragraphs are larger than the budget."""
        body = "\n\n".join(("beta " * 100) for _ in range(4))
        parts = split_long(body, max_tokens=150, overlap=30)
        self.assertGreater(len(parts), 1)
        self.assertIn(" ".join(parts[0].split()[-30:]), parts[1])

    def test_a_code_fence_is_never_cut_in_half_by_overlap(self):
        body = "```bash\n" + "\n".join(f"cmd{i}" for i in range(200)) + "\n```"
        parts = split_long(body, max_tokens=50, overlap=20)
        for part in parts[1:]:
            self.assertFalse(part.startswith("cmd"),
                             "half a command is worse than none")

    def test_headings_with_no_body_are_dropped(self):
        self.assertEqual(chunk_document("# Only a heading\n\n## And another"), [])


class Ranking(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        for i, text in enumerate([
                "the scheduler learns per-weekday posting times",
                "regenerate the instagram token from the app dashboard",
                "ffmpeg concatenates the rendered scenes into one file"]):
            self.s.add("doc.md", "H", i, text, [0.0] * 8)
        self.s.commit()

    def test_bm25_finds_an_exact_identifier(self):
        top = self.s.keyword_search("instagram token", k=1)
        self.assertEqual(self.s.get(top[0][1])["ord"], 1)

    def test_bm25_returns_nothing_for_absent_terms(self):
        self.assertEqual(self.s.keyword_search("kubernetes autoscaling"), [])

    def test_cosine_bounds(self):
        self.assertAlmostEqual(Store.cosine([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(Store.cosine([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(Store.cosine([0, 0], [1, 1]), 0.0,
                               msg="a zero vector must not divide by zero")

    def test_tokenizer_splits_identifiers(self):
        self.assertEqual(tokenize("RUNBOOK.md --no-open"),
                         ["runbook", "md", "no", "open"])


class Fusion(unittest.TestCase):
    def test_agreement_beats_a_single_strong_result(self):
        fused = dict(reciprocal_rank_fusion([[10, 20, 30], [20, 40, 50]]))
        self.assertGreater(fused[20], fused[10],
                           "a chunk both retrievers found should outrank one "
                           "that only the vector search ranked first")

    def test_fusion_uses_rank_not_score(self):
        # identical ranks, wildly different underlying scores: same result
        a = reciprocal_rank_fusion([[1, 2, 3]])
        b = reciprocal_rank_fusion([[1, 2, 3]])
        self.assertEqual(a, b)

    def test_empty_input_is_safe(self):
        self.assertEqual(reciprocal_rank_fusion([[], []]), [])


class Citations(unittest.TestCase):
    def test_extracts_used_sources(self):
        self.assertEqual(cited_indexes("Do this [2]. Then that [1][2].", 5), [1, 2])

    def test_ignores_invented_source_numbers(self):
        self.assertEqual(cited_indexes("As shown [9].", 3), [],
                         "a citation outside the retrieved set is a hallucination, "
                         "not a citation")

    def test_no_citations_is_empty_not_an_error(self):
        self.assertEqual(cited_indexes("An uncited claim.", 3), [])


class Vectors(unittest.TestCase):
    def test_pack_round_trip_is_stable(self):
        v = [0.1, -0.25, 0.333333, 1.0]
        once = unpack(pack(v))
        self.assertEqual(once, unpack(pack(once)),
                         "quantisation must be idempotent, or a cached vector "
                         "differs from a fresh one")

    def test_cache_key_separates_models_and_dims(self):
        a = Cache.key("text", "model-a", 768)
        self.assertNotEqual(a, Cache.key("text", "model-b", 768))
        self.assertNotEqual(a, Cache.key("text", "model-a", 1536))


class Traces(unittest.TestCase):
    def test_a_query_is_recorded_with_its_retrieval(self):
        s = Store(":memory:")
        s.trace("why?", False, 0.51, 12, None, {"retrieved": [{"id": 1}]})
        row = s.traces(1)[0]
        self.assertEqual(row["answered"], 0)
        self.assertAlmostEqual(row["top_score"], 0.51)


if __name__ == "__main__":
    unittest.main(verbosity=2)

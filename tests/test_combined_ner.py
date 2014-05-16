try:
    from unittest import mock
except ImportError:
    import mock

from unittest import TestCase

from iepy.combined_ner import (CombinedNERRunner, NoOverlapCombinedNERRunner,
                               KindPreferenceCombinedNERRunner)

from iepy.models import PreProcessSteps
from .factories import EntityOccurrenceFactory


# helper for defining side effects
def set_result(doc, entities):
    doc.get_preprocess_result.side_effect = lambda x: entities


class TestCombinedNERRunner(TestCase):

    def setUp(self):
        self.runner1 = mock.MagicMock()
        self.runner2 = mock.MagicMock()
        self.doc = mock.MagicMock()
        self.doc.was_preprocess_done.side_effect = lambda x: False

    def test_runners_called_when_not_done_before(self):
        runner1, runner2, doc = self.runner1, self.runner2, self.doc

        runner = CombinedNERRunner([runner1, runner2])
        runner(doc)

        runner1.assert_called_once_with(doc)
        runner2.assert_called_once_with(doc)

    def test_runners_called_when_override(self):
        runner1, runner2, doc = self.runner1, self.runner2, self.doc
        doc.was_preprocess_done.side_effect = lambda x: True

        runner = CombinedNERRunner([runner1, runner2], override=True)
        runner(doc)

        runner1.assert_called_once_with(doc)
        runner2.assert_called_once_with(doc)

    def test_runners_not_called_when_done_before(self):
        runner1, runner2, doc = self.runner1, self.runner2, self.doc
        doc.was_preprocess_done.side_effect = lambda x: True

        runner = CombinedNERRunner([runner1, runner2])
        runner(doc)

        self.assertFalse(runner1.called)
        self.assertFalse(runner2.called)

    def test_no_entities_are_lost(self):
        runner1, runner2, doc = self.runner1, self.runner2, self.doc
        e1 = mock.MagicMock()
        e1.offset = 1
        e2 = mock.MagicMock()
        e2.offset = 2
        runner1.side_effect = lambda doc: set_result(doc, [e1])
        runner2.side_effect = lambda doc: set_result(doc, [e2])

        runner = CombinedNERRunner([runner1, runner2])
        runner(doc)
        doc.set_preprocess_result.assert_called_once_with(PreProcessSteps.ner, [e1, e2])

    def test_can_define_combiner_for_only_one_ner(self):
        runner = CombinedNERRunner([self.runner1])
        runner(self.doc)
        self.assertTrue(self.doc.set_preprocess_result.called)

    def test_can_define_combiner_for_lots_of_ners(self):
        runner1, runner2, doc = self.runner1, self.runner2, self.doc
        runner3, runner4 = mock.MagicMock(), mock.MagicMock()
        runners = [runner1, runner2, runner3, runner4]
        ents = []
        for i, r in enumerate(runners):
            ei = mock.MagicMock()
            ei.offset = i + 1
            ents.append(ei)

        runner1.side_effect = lambda doc: set_result(doc, [ents[0]])
        runner2.side_effect = lambda doc: set_result(doc, [ents[1]])
        runner3.side_effect = lambda doc: set_result(doc, [ents[2]])
        runner4.side_effect = lambda doc: set_result(doc, [ents[3]])

        runner = CombinedNERRunner(runners)
        runner(doc)
        doc.set_preprocess_result.assert_called_once_with(PreProcessSteps.ner, ents)


class TestNEROverlappingHandling(TestCase):

    def setUp(self):
        self.runner1 = mock.MagicMock()
        self.runner2 = mock.MagicMock()
        self.doc = mock.MagicMock()
        self.doc.was_preprocess_done.side_effect = lambda x: False
        self.result1 = self.construct_occurrences(
            [(1, 3, u'X'), (6, 8, u'W'), (8, 9, u'X'), (11, 12, u'W')])
        self.result2 = self.construct_occurrences(
            [(2, 4, u'Y'), (5, 7, u'Z'), (8, 9, u'Y'), (9, 13, u'Z')])
        self.runner1.side_effect = lambda doc: set_result(doc, self.result1)
        self.runner2.side_effect = lambda doc: set_result(doc, self.result2)

    def construct_occurrences(self, data):
        eos = []
        for offset, offset_end, kind in data:
            eos.append(EntityOccurrenceFactory(
                offset=offset, offset_end=offset_end, entity__kind=kind))
        return eos

    def test_overlapped_are_stored_like_that_on_default_combiner(self):
        runner = CombinedNERRunner([self.runner1, self.runner2])
        runner(self.doc)
        self.doc.set_preprocess_result.assert_called_once_with(
            PreProcessSteps.ner, sorted(self.result1 + self.result2))

    def test_simple_overlap_solver_prefers_from_former_subners(self):
        NER = NoOverlapCombinedNERRunner([self.runner1, self.runner2])
        NER(self.doc)
        self.doc.set_preprocess_result.assert_called_once_with(
            PreProcessSteps.ner, self.result1)
        # again, the other way around
        NER = NoOverlapCombinedNERRunner([self.runner2, self.runner1])
        self.doc.reset_mock()
        NER(self.doc)
        self.doc.set_preprocess_result.assert_called_once_with(
            PreProcessSteps.ner, self.result2)

    def test_overlaps_is_solved_prefering_some_kind_over_other(self):
        combiner = lambda rank: KindPreferenceCombinedNERRunner(
            [self.runner1, self.runner2],
            rank=rank
        )
        combiner([u'X', u'W', u'Y', u'Z'])(self.doc)
        self.assertEqual(
            self.doc.set_preprocess_result.call_args_list[-1],
            mock.call(PreProcessSteps.ner, self.result1))

        # Not ranked kinds rank bad
        combiner([u'X', u'W'])(self.doc)
        self.assertEqual(
            self.doc.set_preprocess_result.call_args_list[-1],
            mock.call(PreProcessSteps.ner, self.result1))

        combiner([u'Z', u'Y'])(self.doc)
        self.assertEqual(
            self.doc.set_preprocess_result.call_args_list[-1],
            mock.call(PreProcessSteps.ner, self.result2))

    def test_kindpreference_must_be_instantiated_with_tuple_or_list(self):
        combiner = lambda rank: KindPreferenceCombinedNERRunner(
            [self.runner1, self.runner2],
            rank=rank
        )
        self.assertRaises(ValueError, combiner, 'something')
        self.assertRaises(ValueError, combiner, None)
        self.assertRaises(ValueError, combiner, 1)
        # Not raises
        combiner(('some', 'thing'))
        combiner(['some', 'thing'])
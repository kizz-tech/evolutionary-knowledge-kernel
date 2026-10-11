"""Frozen observation rules: owner text, correction cues, redaction and bounds."""
import unittest

from ekk import observation


class ObservationRuleTests(unittest.TestCase):
    def test_owner_text_drops_host_wrappers_and_injected_turns(self):
        wrapped = '# Files mentioned by the user:\n\n## a.png: /tmp/a.png\n\n## My request for Codex:\n\u043d\u0435 \u0442\u0430\u043a, \u0432\u0435\u0440\u043d\u0438 \u043a\u0430\u043a \u0431\u044b\u043b\u043e'
        self.assertEqual('\u043d\u0435 \u0442\u0430\u043a, \u0432\u0435\u0440\u043d\u0438 \u043a\u0430\u043a \u0431\u044b\u043b\u043e', observation.owner_text(wrapped))
        self.assertEqual('', observation.owner_text('<task-notification>\n<task-id>x</task-id>'))
        self.assertEqual('', observation.owner_text('<heartbeat>'))
        self.assertEqual('', observation.owner_text(None))
        pasted = '\u043f\u043e\u0447\u0435\u043c\u0443 \u0442\u044b \u0443\u0431\u0440\u0430\u043b \u044d\u0442\u043e\n<pasted_content id="1">\u0441\u0442\u043e\u0440\u043e\u043d\u043d\u0438\u0439 \u0442\u0435\u043a\u0441\u0442: \u043d\u0435 \u043d\u0430\u0434\u043e</pasted_content id="1">'
        self.assertEqual('\u043f\u043e\u0447\u0435\u043c\u0443 \u0442\u044b \u0443\u0431\u0440\u0430\u043b \u044d\u0442\u043e', observation.owner_text(pasted))

    def test_correction_cues_in_russian_and_english(self):
        for text in ('\u043d\u0435\u0442, \u044f \u0436\u0435 \u043f\u0440\u043e\u0441\u0438\u043b \u0431\u0435\u0437 worktree', '\u043d\u0435 \u043d\u0430\u0434\u043e \u0443\u0441\u043b\u043e\u0436\u043d\u044f\u0442\u044c, \u0443\u0431\u0435\u0440\u0438 \u044d\u0442\u043e', '\u0437\u0430\u0447\u0435\u043c \u0442\u044b \u044d\u0442\u043e \u0441\u0434\u0435\u043b\u0430\u043b?',
                     'No, revert that', "don't touch the config", '\u043e\u043f\u044f\u0442\u044c \u0437\u0430\u0431\u044b\u043b \u043e\u0442\u0447\u0451\u0442 \u0432 \u0442\u0433', '\u044d\u0442\u043e \u043a\u0440\u0438\u0432\u043e'):
            self.assertTrue(observation.is_correction(text), text)
        for text in ('\u0441\u0434\u0435\u043b\u0430\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u043e\u043f\u043b\u0430\u0442\u044b', 'what is the current token policy?', 'ok, \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0439',
                     'user@example.com \u043f\u0438\u0448\u0435\u0442: \u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \u043e\u043f\u043b\u0430\u0442\u0430', '\u043d\u0435\u0442 ' + 'x' * 600, ''):
            self.assertFalse(observation.is_correction(text), text)

    def test_repeat_marker_needs_a_correction(self):
        self.assertTrue(observation.is_repeat('\u044f \u0436\u0435 \u0433\u043e\u0432\u043e\u0440\u0438\u043b: \u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u0439 \u043f\u0440\u043e\u0434'))
        self.assertTrue(observation.is_repeat('\u043e\u043f\u044f\u0442\u044c \u043d\u0435 \u0442\u0430\u043a'))
        self.assertFalse(observation.is_repeat('\u043d\u0435 \u0442\u0430\u043a'))
        self.assertFalse(observation.is_repeat('\u0441\u0434\u0435\u043b\u0430\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437 \u043e\u0442\u0447\u0451\u0442'))

    def test_rule_2_excludes_more_host_texts_and_everything_rule_1_excludes(self):
        rule_2 = observation.RULE_2
        for text in ('<cross-session-message from="uds:/tmp/a.sock" from-name="Other agent">FYI: committed again</cross-session-message>',
                     '<send_user_message_question_reply> [{"question": "Ship it?", "answer": "\u043d\u0435\u0442"}] '
                     '</send_user_message_question_reply>',
                     '<scheduled-task name="weekly" file="/tmp/SKILL.md">This is an automated run.</scheduled-task>'):
            self.assertEqual(text, observation.owner_text(text))
            self.assertEqual('', observation.owner_text(text, rule_2), text)
        for text in ('<task-notification>\n<task-id>x</task-id>', '<heartbeat>', '[Request interrupted by user]',
                     'This session is being continued from a previous conversation.', 'Try again',
                     'I hit my usage limit', '<command-name>/clear</command-name>', '<system-reminder>x</system-reminder>',
                     '<local-command-stdout>ok</local-command-stdout>', '<bash-input>ls</bash-input>', None):
            self.assertEqual('', observation.owner_text(text), text)
            self.assertEqual('', observation.owner_text(text, rule_2), text)
        # The artifact view context is the host's block before the owner's own words.
        framed = '<artifact-view-context artifact="a1">{"selected": ["' + 'x' * 600 + '"]}</artifact-view-context>\n\n\u0443\u0431\u0435\u0440\u0438 \u043b\u0438\u0448\u043d\u0435\u0435'
        self.assertEqual('\u0443\u0431\u0435\u0440\u0438 \u043b\u0438\u0448\u043d\u0435\u0435', observation.owner_text(framed, rule_2))
        self.assertFalse(observation.is_correction(observation.owner_text(framed)))
        self.assertTrue(observation.is_correction(observation.owner_text(framed, rule_2), rule_2))
        # Rule 1's blocks go first, so the context still leads what remains; elsewhere it is the owner's text.
        self.assertEqual('\u0443\u0431\u0435\u0440\u0438 \u043b\u0438\u0448\u043d\u0435\u0435', observation.owner_text(
            '<system-reminder>x</system-reminder>\n<artifact-view-context a="1">ctx</artifact-view-context>\n\n\u0443\u0431\u0435\u0440\u0438 \u043b\u0438\u0448\u043d\u0435\u0435', rule_2))
        quoted = '\u0443\u0431\u0435\u0440\u0438 \u044d\u0442\u043e: <artifact-view-context a="1">ctx</artifact-view-context>'
        self.assertEqual(quoted, observation.owner_text(quoted, rule_2))

    def test_rule_2_reads_long_prompts_in_linear_time(self):
        import time
        for text in ('<artifact-view-context ' * 20000, 'hi ' + '<artifact-view-context ' * 20000):
            started = time.perf_counter()
            observation.owner_text(text, observation.RULE_2)
            self.assertLess(time.perf_counter() - started, 0.5)

    def test_rule_2_reads_the_you_cue_at_a_word_boundary(self):
        rule_2 = observation.RULE_2
        # Synthetic shapes: a Russian word ending in the letters of "you" before "not…".
        for text in ('\u043e\u0431\u043d\u043e\u0432\u0438 \u0433\u0440\u0430\u0444\u0438\u043a\u0438, \u043e\u0442\u0432\u0435\u0442\u044b \u043d\u0435\u043c\u043d\u043e\u0433\u043e \u043f\u043e\u0437\u0436\u0435', '\u0441\u043e\u0431\u0435\u0440\u0438 \u043e\u0442\u0447\u0451\u0442\u044b \u043d\u0435\u043f\u043e\u0441\u0440\u0435\u0434\u0441\u0442\u0432\u0435\u043d\u043d\u043e \u0438\u0437 \u0431\u0430\u0437\u044b'):
            self.assertTrue(observation.is_correction(text), text)
            self.assertFalse(observation.is_correction(text, rule_2), text)
        for text in ('\u0442\u044b \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u043b \u0441\u0431\u043e\u0440\u043a\u0443', '\u0422\u044b \u0437\u0430\u0431\u044b\u043b \u043e\u0442\u0447\u0451\u0442', '\u043f\u043e\u0447\u0435\u043c\u0443 \u0442\u044b \u043e\u0441\u0442\u0430\u0432\u0438\u043b \u0441\u0442\u0430\u0440\u043e\u0435'):
            self.assertTrue(observation.is_correction(text, rule_2), text)

    def test_rule_2_repeat_phrases(self):
        rule_2 = observation.RULE_2
        for text in ('\u043d\u0435 \u0442\u0430\u043a, \u0432 \u043f\u0440\u043e\u0448\u043b\u044b\u0439 \u0440\u0430\u0437 \u0431\u044b\u043b\u043e \u0438\u043d\u0430\u0447\u0435', '\u043d\u0435\u0442, \u0432 \u043f\u0440\u043e\u0448\u043b\u044b\u0435 \u0440\u0430\u0437\u044b \u0442\u043e\u0436\u0435', '\u043d\u0435 \u043d\u0430\u0434\u043e, \u0432 \u043f\u0440\u043e\u0448\u043b\u0439 \u0440\u0430\u0437 \u0443\u0436\u0435 \u043e\u0431\u0441\u0443\u0436\u0434\u0430\u043b\u0438',
                     '\u0437\u0430\u0447\u0435\u043c \u0434\u043e\u0431\u0430\u0432\u0438\u043b \u043c\u043e\u043a\u0438? \u044f \u0432\u0435\u0434\u044c \u0442\u0435\u0431\u0435 \u0437\u0430\u0440\u0430\u043d\u0435\u0435 \u043f\u0438\u0441\u0430\u043b', '\u043f\u043e\u0447\u0435\u043c\u0443 \u0442\u044b \u043d\u0435 \u043e\u0431\u043d\u043e\u0432\u0438\u043b \u0437\u0430\u0432\u0438\u0441\u0438\u043c\u043e\u0441\u0442\u0438? \u044f \u0436\u0435 \u043f\u043e\u043f\u0440\u043e\u0441\u0438\u043b',
                     '\u0441\u043a\u043e\u043b\u044c\u043a\u043e \u043c\u043e\u0436\u043d\u043e, \u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u0439 \u043a\u043e\u043d\u0444\u0438\u0433', '\u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u0439, \u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0440\u0430\u0437 \u0442\u0435\u0431\u0435 \u0433\u043e\u0432\u043e\u0440\u0438\u0442\u044c', '\u0432 \u043a\u043e\u0442\u043e\u0440\u044b\u0439 \u0440\u0430\u0437 \u043d\u0435 \u0442\u0430\u043a',
                     '\u0441\u043d\u043e\u0432\u0430 \u0441\u043b\u043e\u043c\u0430\u043b \u0441\u0431\u043e\u0440\u043a\u0443, \u0432\u0435\u0440\u043d\u0438'):
            self.assertTrue(observation.is_repeat(text, rule_2), text)
            self.assertFalse(observation.is_repeat(text), text)
        for text in ('\u044f \u043d\u0435 \u043f\u0440\u043e\u0441\u0438\u043b \u044d\u0442\u043e \u0443\u0434\u0430\u043b\u044f\u0442\u044c', '\u043d\u0435 \u0442\u0430\u043a', '\u0441\u0434\u0435\u043b\u0430\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437 \u043e\u0442\u0447\u0451\u0442', '\u0441\u043d\u043e\u0432\u0430 \u0437\u0430\u043f\u0443\u0441\u0442\u0438 \u0442\u0435\u0441\u0442\u044b',
                     '\u043d\u0435 \u0442\u0430\u043a, \u0432 \u043f\u0440\u043e\u0448\u043b\u043e\u043c \u0440\u0430\u0437\u0434\u0435\u043b\u0435 \u0431\u044b\u043b\u043e \u0438\u043d\u0430\u0447\u0435', '\u043b\u0438\u0448\u043d\u0435\u0435, \u044f \u0436\u0435 \u043f\u043e\u0433\u043e\u0432\u043e\u0440\u0438\u043b \u0441 \u043d\u0438\u043c\u0438',
                     '\u043d\u0435 \u0442\u0430\u043a, \u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0440\u0430\u0437 \u0432\u044b\u0437\u044b\u0432\u0430\u0435\u0442\u0441\u044f \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a?'):
            self.assertFalse(observation.is_repeat(text, rule_2), text)
        # A repeat phrase counts only in what the same rule reads as a correction.
        only_rule_1 = '\u043e\u0431\u043d\u043e\u0432\u0438 \u0433\u0440\u0430\u0444\u0438\u043a\u0438, \u043e\u0442\u0432\u0435\u0442\u044b \u043d\u0435\u043c\u043d\u043e\u0433\u043e \u043f\u043e\u0437\u0436\u0435, \u0441\u043d\u043e\u0432\u0430'
        self.assertTrue(observation.is_correction(only_rule_1) and observation.RULE_2.repeat.search(only_rule_1))
        self.assertFalse(observation.is_repeat(only_rule_1, rule_2))
        # What rule 1 counts as a repeat, rule 2 counts too.
        for text in ('\u044f \u0436\u0435 \u0433\u043e\u0432\u043e\u0440\u0438\u043b: \u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u0439 \u043f\u0440\u043e\u0434', '\u043e\u043f\u044f\u0442\u044c \u043d\u0435 \u0442\u0430\u043a', '\u043d\u0435\u0442, 3-\u0438\u0439 \u0440\u0430\u0437 \u043f\u0440\u043e\u0448\u0443'):
            self.assertTrue(observation.is_repeat(text), text)
            self.assertTrue(observation.is_repeat(text, rule_2), text)

    def test_redaction_keeps_references_and_removes_credentials(self):
        commit = '622cf3f1d9deca77ca97f6d39a8607b277c299ab'
        text = ('commit ' + commit + ' in src/ekk/adapters/operation_diagnostics.py; '
                'key sk-abcdefghijklmnop1234567890; api_key = "A1b2C3d4E5f6G7h8"; write to owner@example.com; '
                'token rollover policy stays; Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123')
        redacted = observation.redact(text)
        self.assertIn(commit, redacted)
        self.assertIn('src/ekk/adapters/operation_diagnostics.py', redacted)
        self.assertIn('token rollover policy stays', redacted)
        for secret in ('sk-abcdefghijklmnop1234567890', 'A1b2C3d4E5f6G7h8', 'owner@example.com', 'eyJhbGciOiJIUzI1NiJ9'):
            self.assertNotIn(secret, redacted)

    def test_bounds_and_headline(self):
        text, cut = observation.bounded('a' * 50, 20)
        self.assertTrue(cut)
        self.assertTrue(text.endswith('[truncated]'))
        self.assertEqual(('short', False), observation.bounded('short', 20))
        self.assertEqual('Payout minimum raised to 3000 RUB.', observation.headline('## **Payout minimum raised to 3000 RUB.** Tests pass.\n\nDetails'))
        self.assertEqual('', observation.headline('\n\n--\n'))
        self.assertLessEqual(len(observation.headline('word ' * 80)), observation.MAX_TITLE_CHARS)


if __name__ == '__main__':
    unittest.main()

import copy
import unittest
from unittest.mock import patch
import watcher


class TrackerTests(unittest.TestCase):
    def parse(self, text):
        return watcher.parse_github_table(text, {'cycle_year': '2027', 'season': 'Summer'})

    def test_html_official_link_entities_and_continuation(self):
        text = '''<table><tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th></tr>
        <tr><td><b>Acme</b></td><td>Software Intern</td><td>Boston<br>NYC</td>
        <td><a href="https://simplify.jobs/p/1"><img src="https://images/badge"></a>
        <a href="https://careers.acme.com/1?a=1&amp;b=2">Apply</a></td></tr>
        <tr><td>↳</td><td>FPGA Intern</td><td>Austin, TX</td><td><a href="https://careers.acme.com/2">Apply</a></td></tr>
        <tr><td>↳</td><td>AI Intern</td><td>NYC</td><td>🔒 <a href="https://careers.acme.com/3">Old</a></td></tr></table>'''
        jobs = self.parse(text)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[1]['company'], 'Acme')
        self.assertEqual(jobs[0]['url'], 'https://careers.acme.com/1?a=1&b=2')
        self.assertIn('Summer 2027', jobs[0]['year_text'])

    def test_markdown_pay_column_and_closed(self):
        jobs = self.parse('''| Company | Role | Location | Salary | Application | Age |
| --- | --- | --- | --- | --- | --- |
| Acme | Robotics Intern | Boston | $40 | [Apply](https://acme.com/1) | 1d |
| ↳ | Software Intern | Boston | $40 | Closed [Apply](https://acme.com/2) | 2d |''')
        self.assertEqual([j['url'] for j in jobs], ['https://acme.com/1'])

    def test_missing_schema_is_failure_but_all_closed_is_valid(self):
        with self.assertRaises(ValueError):
            self.parse('<html>Rate limited</html>')
        self.assertEqual(self.parse('| Acme | Software Intern | Boston | 🔒 | 1d |'), [])
        with self.assertRaises(ValueError):
            self.parse('| Acme | Software Intern | Boston | Broken button | 1d |')

    def test_json_closed_and_invalid_schema(self):
        from types import SimpleNamespace
        rows = [dict(title='Software Intern', company='Acme', url='https://acme.com/1', status='closed'),
                dict(title='Software Intern', company='Acme', url='https://acme.com/2', active=False),
                dict(title='FPGA Intern', company='Acme', url='https://acme.com/3', terms=['Summer'])]
        with patch.object(watcher.requests, 'get', create=True, return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: rows)):
            jobs = watcher.fetch_github_json({'url': 'https://example.com', 'cycle_year': '2027'})
        self.assertEqual([j['url'] for j in jobs], ['https://acme.com/3'])
        with patch.object(watcher.requests, 'get', create=True, return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {'error': 'rate limited'})):
            with self.assertRaises(ValueError):
                watcher.fetch_github_json({'url': 'https://example.com'})

    def test_tracking_parameters_and_ashby_share_keys(self):
        pairs = [
            ('https://acme.com/job/1?utm_source=GH&ref=Simplify&id=2', 'https://acme.com/job/1?id=2'),
            ('https://jobs.ashbyhq.com/acme/12345678-abcd-abcd-abcd-123456789abc/application',
             'https://jobs.ashbyhq.com/acme/12345678-abcd-abcd-abcd-123456789abc'),
        ]
        for a, b in pairs:
            self.assertEqual(watcher.canonical_job_key('a', {'url': a}), watcher.canonical_job_key('b', {'url': b}))

    def sweep(self, config, state, jobs):
        saved = {}
        with patch.object(watcher, 'load_config', return_value=config), \
             patch.object(watcher, 'load_json', return_value=state), \
             patch.dict(watcher.FETCHERS, {'github_md': lambda f: copy.deepcopy(jobs)}), \
             patch.object(watcher, 'save_json', side_effect=lambda path, value: saved.update(value)), \
             patch.object(watcher, 'write_open_roles') as report, \
             patch.object(watcher, 'write_top_picks'), \
             patch.object(watcher, 'send_email') as email, patch.object(watcher.time, 'sleep'):
            watcher.main()
        return saved, email.call_count, report.call_count

    def test_baseline_new_role_closed_and_cross_source_history(self):
        config = {'firms': [{'name': 'Tracker', 'ats': 'github_md'}]}
        job = {'id': '1', 'title': 'Software Intern', 'company': 'Acme', 'location': 'Boston, MA',
               'url': 'https://acme.com/1', 'bypass_filters': True}
        state, emails, _ = self.sweep(config, {}, [job])
        self.assertEqual(emails, 0)
        state, emails, _ = self.sweep(config, state, [dict(job, url='https://other.com/1')])
        self.assertEqual(emails, 0)
        state, emails, _ = self.sweep(config, state, [dict(job, title='FPGA Intern', url='https://acme.com/2')])
        self.assertEqual(emails, 1)
        state, emails, _ = self.sweep(config, state, [])
        self.assertEqual(emails, 0)
        self.assertIn('https://acme.com/1', state)

    def test_added_source_is_silent_with_existing_state(self):
        config = {'firms': [{'name': 'New tracker', 'ats': 'github_md'}]}
        job = {'id': '1', 'title': 'Software Intern', 'company': 'Acme', 'location': 'NYC',
               'url': 'https://acme.com/1', 'bypass_filters': True}
        state, emails, _ = self.sweep(config, {'old-key': {}}, [job])
        self.assertEqual(emails, 0)
        self.assertIn(watcher.SOURCE_PREFIX + 'new tracker', state)

    def test_failure_does_not_warm_or_replace_reports(self):
        config = {'firms': [{'name': 'Tracker', 'ats': 'github_md', 'critical': True}]}
        with patch.object(watcher, 'load_config', return_value=config), \
             patch.object(watcher, 'load_json', return_value={}), \
             patch.dict(watcher.FETCHERS, {'github_md': lambda f: self.parse('invalid')}), \
             patch.object(watcher, 'save_json') as save, \
             patch.object(watcher, 'write_open_roles') as report, \
             patch.object(watcher, 'write_top_picks'), patch.object(watcher, 'send_email') as email:
            watcher.main()
        self.assertEqual(save.call_args.args[1], {})
        report.assert_not_called()
        email.assert_not_called()


if __name__ == '__main__':
    unittest.main()

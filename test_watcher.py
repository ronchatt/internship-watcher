import sys
import types
import unittest
import json

sys.modules.setdefault("requests", types.SimpleNamespace())
import watcher


class WatcherPersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.filters = {
            "title_keywords": ["intern", "internship", "co-op", "coop"],
            "title_require_any": [
                "software", "embedded", "firmware", "hardware", "fpga", "asic",
                "electrical", "rtl", "verification", "robotics", "controls",
                "systems", "architecture", "machine learning", "ai",
            ],
            "title_exclude": ["sales", "marketing", "help desk", "human resources"],
            "years": ["2027"],
            "minimum_hourly_compensation": 30,
            "compensation_exempt_companies": ["Google", "Apple", "Meta", "Netflix", "Amazon"],
            "reject_cycle_phrases": ["summer 2026", "spring 2026", "fall 2026"],
            "location_exclude": [],
        }

    def test_spring_coop_is_relevant(self):
        job = {"title": "Embedded Software Co-op - Spring 2027", "content": "", "location": "Boston, MA"}
        self.assertTrue(watcher.is_relevant(job, self.filters))

    def test_hardware_roles_are_relevant(self):
        for title in (
            "FPGA Design Intern - Summer 2027",
            "ASIC Verification Intern",
            "Electrical Engineering Intern",
            "Computer Architecture Intern",
        ):
            with self.subTest(title=title):
                self.assertTrue(watcher.is_relevant({"title": title, "content": "", "location": ""}, self.filters))

    def test_nontechnical_roles_still_drop(self):
        self.assertFalse(watcher.is_relevant(
            {"title": "Sales and Marketing Intern 2027", "content": "", "location": "New York, NY"},
            self.filters,
        ))

    def test_selective_technical_consulting_is_relevant(self):
        filters = dict(self.filters)
        filters["title_require_any"] = self.filters["title_require_any"] + [
            "technology", "forward deployed", "solutions engineer"
        ]
        for title in (
            "Technology Consulting Intern - Summer 2027",
            "Forward Deployed Engineer Internship - Summer 2027",
            "AI Solutions Engineer Intern 2027",
        ):
            with self.subTest(title=title):
                self.assertTrue(watcher.is_relevant(
                    {"title": title, "content": "", "location": "New York, NY"}, filters
                ))

    def test_generic_business_consulting_is_rejected(self):
        filters = dict(self.filters)
        filters["title_require_any"] = self.filters["title_require_any"] + ["technology"]
        filters["title_exclude"] = self.filters["title_exclude"] + [
            "management consulting", "business consulting", "strategy consulting"
        ]
        self.assertFalse(watcher.is_relevant(
            {"title": "Management Consulting Intern 2027", "content": "", "location": "Chicago, IL"},
            filters,
        ))

    def test_roblox_parser_reads_server_rendered_cards(self):
        html = '''<a href="/jobs/123" class="card"><p class="body--large">Software Engineer Intern - Summer 2027</p>
        <span class="caption">San Mateo, CA, United States</span></a>'''
        response = types.SimpleNamespace(text=html, raise_for_status=lambda: None)
        old_get = getattr(watcher.requests, "get", None)
        watcher.requests.get = lambda *args, **kwargs: response
        try:
            jobs = watcher.fetch_roblox({})
        finally:
            if old_get is None:
                del watcher.requests.get
            else:
                watcher.requests.get = old_get
        self.assertEqual(jobs[0]["id"], "123")
        self.assertEqual(jobs[0]["location"], "San Mateo, CA, United States")

    def test_capital_one_parser_reads_server_rendered_cards(self):
        html = '''<a href="/job/mclean/technology-intern/1/456" data-job-id="456">
        <h2>Technology Internship Program - Summer 2027</h2>
        <span class="job-location">McLean, VA</span></a>'''
        response = types.SimpleNamespace(text=html, raise_for_status=lambda: None)
        old_get = getattr(watcher.requests, "get", None)
        watcher.requests.get = lambda *args, **kwargs: response
        try:
            jobs = watcher.fetch_capitalone({"max_pages": 1})
        finally:
            if old_get is None:
                del watcher.requests.get
            else:
                watcher.requests.get = old_get
        self.assertEqual(jobs[0]["id"], "456")
        self.assertIn("Summer 2027", jobs[0]["title"])

    def test_quant_only_role_drops(self):
        self.assertFalse(watcher.is_relevant(
            {"title": "Quantitative Trading Intern 2027", "content": "", "location": "New York, NY"},
            self.filters,
        ))

    def test_wrong_year_in_url_drops(self):
        job = {
            "title": "Software Development Engineer Intern/Co-op",
            "content": "Current university internship opportunity.",
            "location": "Seattle, WA",
            "url": "https://example.com/software-intern-2026",
        }
        self.assertFalse(watcher.is_relevant(job, self.filters))

    def test_yc_parser_marks_public_jobs_as_startup_internships(self):
        page = '''<html><title>Internships at YC Companies, Summer 2027</title>
        <div>Acme Robotics W26 · Robotics
        <a href="/companies/acme-robotics/jobs/abc123-software-engineer">Software Engineer</a>
        San Francisco, CA · Internship · $45/hour</div></html>'''
        jobs = watcher._parse_yc_internships_html(page)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Acme Robotics")
        self.assertTrue(jobs[0]["is_internship"])
        self.assertTrue(jobs[0]["startup"])
        self.assertIn("summer 2027", jobs[0]["year_text"].lower())
        self.assertTrue(watcher.is_relevant(jobs[0], self.filters))

    def test_yc_old_collection_is_rejected(self):
        page = '''<title>Internships at YC Companies, Summer 2026</title>
        <a href="/companies/acme/jobs/1-software-engineer">Software Engineer</a>'''
        job = watcher._parse_yc_internships_html(page)[0]
        self.assertFalse(watcher.is_relevant(job, self.filters))

    def test_explicitly_unpaid_role_is_rejected(self):
        job = {"title": "Software Intern 2027", "content": "This is an unpaid internship.", "location": ""}
        self.assertFalse(watcher.is_relevant(job, self.filters))

    def test_explicit_pay_below_floor_is_rejected(self):
        job = {"title": "Software Intern 2027", "content": "Pay is $24-$28 per hour.", "location": "Austin, TX"}
        self.assertFalse(watcher.is_relevant(job, self.filters))

    def test_unknown_pay_and_range_reaching_floor_are_retained(self):
        unknown = {"title": "Firmware Intern 2027", "content": "", "location": "Boston, MA"}
        ranged = {"title": "Firmware Intern 2027", "content": "Pay is $22 to $35 per hour.", "location": "Boston, MA"}
        self.assertTrue(watcher.is_relevant(unknown, self.filters))
        self.assertTrue(watcher.is_relevant(ranged, self.filters))

    def test_faang_is_exempt_from_pay_floor(self):
        job = {"title": "Software Intern 2027", "company": "Page: Google Careers (interns)", "content": "Pay is $25/hour.", "location": "Seattle, WA"}
        self.assertTrue(watcher.is_relevant(job, self.filters))

    def test_elite_engineering_company_and_startup_bypass_pay_floor(self):
        filters = dict(self.filters)
        filters["compensation_exempt_companies"] = ["SpaceX"]
        spacex = {"title": "Software Intern 2027", "company": "SpaceX", "content": "Pay is $25/hour.", "location": "CA"}
        startup = {"title": "Software Backend Intern 2027", "company": "Tiny AI", "startup": True, "content": "Pay is $25/hour.", "location": "NY"}
        self.assertTrue(watcher.is_relevant(spacex, filters))
        self.assertTrue(watcher.is_relevant(startup, filters))

    def test_trading_firm_engineering_stays_but_pure_quant_drops(self):
        filters = dict(self.filters)
        filters["quant_role_exclude"] = ["quantitative researcher", "quantitative trader"]
        engineer = {"title": "Software Engineering Intern 2027", "company": "Quant: Jane Street", "content": "Infrastructure systems", "location": "New York, NY"}
        researcher = {"title": "Quantitative Researcher Intern 2027", "company": "Quant: Jane Street", "content": "", "location": "New York, NY"}
        self.assertTrue(watcher.is_relevant(engineer, filters))
        self.assertFalse(watcher.is_relevant(researcher, filters))

    def test_actual_strategy_prioritizes_software_over_hardware(self):
        with open("config.json", encoding="utf-8") as handle:
            profile = json.load(handle)["ranking"]
        software = watcher.score_job({"title": "Software Engineering Intern", "content": "", "location": ""}, profile)
        hardware = watcher.score_job({"title": "ASIC Design Intern", "content": "", "location": ""}, profile)
        self.assertGreater(software["score"], hardware["score"])

    def test_value_routes_explain_brand_pay_and_trading_stretch(self):
        with open("config.json", encoding="utf-8") as handle:
            profile = json.load(handle)["ranking"]
        job = {"title": "Software Engineering Intern", "company": "Quant: Jane Street", "content": "Pay is $60/hour.", "location": "New York, NY"}
        scored = watcher.score_job(job, profile)
        self.assertIn("HIGH COMPENSATION", scored["value_routes"])
        self.assertIn("TRADING-FIRM ENGINEERING — STRETCH", scored["value_routes"])
        self.assertEqual(scored["tier"], "QUANT ENGINEERING STRETCH")

    def test_quant_does_not_crowd_nonquant_out_of_capped_email(self):
        nonquant = {
            "title": "Infrastructure Intern", "company": "Great Cloud Co",
            "location": "Seattle, WA", "url": "https://example.com/nonquant",
            "tier": "GOOD MATCH", "score": 35, "reasons": [],
            "trading_stretch": False,
        }
        quant = [{
            "title": f"Software Intern {i}", "company": "Quant: Jane Street",
            "location": "New York, NY", "url": f"https://example.com/quant/{i}",
            "tier": "QUANT ENGINEERING STRETCH", "score": 80 - i,
            "reasons": [], "trading_stretch": True,
        } for i in range(30)]
        html = watcher.build_email_html({"mixed": quant + [nonquant]}, max_roles=25)
        self.assertIn("https://example.com/nonquant", html)
        self.assertIn("QUANT-FIRM ENGINEERING", html)
        self.assertEqual(html.count("https://example.com/quant/"), 24)

    def test_annual_salary_range_is_converted(self):
        rtx = {"title": "Software Intern 2027", "content": "Salary range is 37,000 USD - 82,000 USD.", "location": "Dallas, TX"}
        low = {"title": "Software Intern 2027", "content": "Salary range is 37,000 USD - 50,000 USD.", "location": "Dallas, TX"}
        self.assertTrue(watcher.is_relevant(rtx, self.filters))
        self.assertFalse(watcher.is_relevant(low, self.filters))

    def test_greenhouse_url_variants_share_a_canonical_key(self):
        one = {"id": "5148079007", "url": "https://boards.greenhouse.io/andurilindustries/jobs/5148079007?gh_jid=5148079007"}
        two = {"id": "5148079007", "url": "https://job-boards.greenhouse.io/andurilindustries/jobs/5148079007"}
        self.assertEqual(watcher.canonical_job_key("Anduril", one), watcher.canonical_job_key("andurilindustries", two))

    def test_workday_locale_variants_share_a_canonical_key(self):
        en = {"id": "x", "url": "https://example.wd5.myworkdayjobs.com/en-US/site/job/Texas/Software-Intern_R015667"}
        fr = {"id": "y", "url": "https://example.wd5.myworkdayjobs.com/fr-CA/other/job/Texas/Software-Intern_R015667"}
        self.assertEqual(watcher.canonical_job_key("Example", en), watcher.canonical_job_key("Example", fr))
        self.assertEqual(watcher.canonical_job_key("Example", en), "workday:example.wd5.myworkdayjobs.com:r015667")

    def test_generic_samsung_workday_program_uses_description(self):
        listing = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "total": 1,
                "jobPostings": [{
                    "title": "2027 Summer Internship",
                    "locationsText": "1530 FM 973 Taylor, TX, USA",
                    "externalPath": "/job/1530-FM-973-Taylor-TX-USA/XMLNAME-2027-Summer-Internship_R119158",
                }],
            },
        )
        detail = types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"jobPostingInfo": {
                "location": "1530 FM 973 Taylor, TX, USA",
                "jobDescription": (
                    "<p>Engineering students work on real-world semiconductor hardware "
                    "projects. Majors include Computer Science and Computer Engineering.</p>"
                ),
            }},
        )
        old_post = getattr(watcher.requests, "post", None)
        old_get = getattr(watcher.requests, "get", None)
        watcher.requests.post = lambda *args, **kwargs: listing
        watcher.requests.get = lambda *args, **kwargs: detail
        try:
            jobs = watcher.fetch_workday({
                "name": "Samsung Austin Semiconductor",
                "host": "sec.wd3.myworkdayjobs.com",
                "tenant": "sec",
                "site": "Samsung_Careers",
                "locale": "en-US",
                "search_text": "intern",
            })
        finally:
            if old_post is None:
                del watcher.requests.post
            else:
                watcher.requests.post = old_post
            if old_get is None:
                del watcher.requests.get
            else:
                watcher.requests.get = old_get

        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["broad_program"])
        self.assertIn("computer engineering", jobs[0]["content"].lower())
        jobs[0]["company"] = "Samsung Austin Semiconductor"
        self.assertTrue(watcher.is_relevant(jobs[0], self.filters))

    def test_generic_program_is_labeled_as_uncertain_not_exact_fit(self):
        with open("config.json", encoding="utf-8") as handle:
            profile = json.load(handle)["ranking"]
        job = {
            "title": "2027 Summer Internship",
            "company": "Samsung Austin Semiconductor",
            "content": "Computer engineering students work on semiconductor hardware projects.",
            "location": "Taylor, TX, USA",
            "broad_program": True,
        }
        scored = watcher.score_job(job, profile)
        self.assertIn("BROAD TECHNICAL PROGRAM", scored["value_routes"])
        self.assertTrue(any("exact team/assignment unknown" in reason for reason in scored["reasons"]))

    def test_foreign_iso_country_code_is_rejected(self):
        self.assertFalse(watcher._is_us_location("Abstatt, BW, de"))
        self.assertFalse(watcher._is_us_location("Toronto, ON, CA"))
        self.assertTrue(watcher._is_us_location("Charleston, SC, us"))
        self.assertTrue(watcher._is_us_location("New York, NY; London, UK"))

    def test_foreign_title_is_rejected_despite_generic_location(self):
        job = {"title": "Software Engineering Intern - India", "location": "Multiple Locations", "url": "https://example.com/1"}
        self.assertFalse(watcher._is_us_job(job))

    def test_foreign_description_is_rejected_when_location_missing(self):
        job = {"title": "Software Engineering Intern", "location": "", "content": "This role is based in London, United Kingdom.", "url": "https://example.com/2"}
        self.assertFalse(watcher._is_us_job(job))

    def test_workday_locale_does_not_look_like_foreign_location(self):
        job = {"title": "Software Engineering Intern", "location": "Austin, TX", "url": "https://example.wd5.myworkdayjobs.com/fr-CA/site/job/US-TX/Intern_R123"}
        self.assertTrue(watcher._is_us_job(job))

    def test_digest_sources_are_classified_separately(self):
        self.assertTrue(watcher._is_digest_source({"name": "Competition: Example"}))
        self.assertTrue(watcher._is_digest_source({"name": "Page: Example", "digest": True}))
        self.assertFalse(watcher._is_digest_source({"name": "Page: AMD internships"}))

    def test_email_uses_discovery_wording(self):
        job = {"title": "Software Intern", "company": "Example", "location": "",
               "url": "https://example.com/1", "tier": "GOOD MATCH", "score": 30}
        html = watcher.build_email_html({"Example": [job]})
        self.assertIn("newly discovered", html)
        self.assertNotIn("just opened", html)

    def test_seen_state_migration_prevents_duplicate_alerts(self):
        old_url = "https://boards.greenhouse.io/andurilindustries/jobs/5148079007?gh_jid=5148079007"
        migrated = watcher.canonicalize_seen_state({old_url: {"title": "Software Intern", "url": old_url}})
        self.assertIn("greenhouse:5148079007", migrated)
        self.assertEqual(len(migrated), 1)

    def test_source_markers_survive_state_migration(self):
        marker = watcher.SOURCE_PREFIX + "spacex"
        migrated = watcher.canonicalize_seen_state({marker: {"warmed": True}})
        self.assertEqual(migrated[marker], {"warmed": True})

    def test_generic_title_can_use_technical_description(self):
        job = {
            "title": "Engineering Intern - Summer 2027",
            "content": "Develop embedded firmware for autonomous robotic systems.",
            "location": "El Segundo, CA",
        }
        self.assertTrue(watcher.is_relevant(job, self.filters))

    def test_unknown_compensation_is_neutral(self):
        profile = {"role_weights": {"embedded": 30}, "role_keywords": {"embedded": ["embedded", "firmware"]}}
        job = {"title": "Embedded Firmware Intern - Summer 2027", "content": "", "location": "Austin, TX"}
        scored = watcher.score_job(job, profile)
        self.assertFalse(any("compensation" in reason.lower() for reason in scored["reasons"]))

    def test_listed_hourly_compensation_is_a_soft_bonus(self):
        profile = {
            "role_weights": {"software": 34},
            "role_keywords": {"software": ["software"]},
            "compensation_hourly_bonuses": {"40": 4, "50": 6, "60": 8},
        }
        job = {
            "title": "Software Engineering Intern",
            "content": "The pay range for this role is $50 to $60 per hour.",
            "location": "",
        }
        scored = watcher.score_job(job, profile)
        self.assertEqual(scored["hourly_compensation"], 55.0)
        self.assertEqual(scored["score"], 40)

    def test_location_changes_rank_but_not_relevance(self):
        profile = {
            "role_weights": {"software": 30},
            "role_keywords": {"software": ["software"]},
            "location_weights": {"preferred_hub": 5, "other_us": 0},
            "preferred_locations": ["seattle"],
        }
        seattle = watcher.score_job(
            {"title": "Software Engineering Intern", "content": "", "location": "Seattle, WA"}, profile
        )
        des_moines = watcher.score_job(
            {"title": "Software Engineering Intern", "content": "", "location": "Des Moines, IA"}, profile
        )
        self.assertGreater(seattle["score"], des_moines["score"])
        self.assertEqual(des_moines["tier"], "GOOD MATCH")

    def test_email_uses_fit_tiers_not_quant_categories(self):
        job = {
            "title": "FPGA Design Intern - Summer 2027",
            "company": "Example Semiconductor",
            "content": "",
            "location": "Austin, TX",
            "url": "https://example.com/job",
            "tier": "HIGH PRIORITY",
            "score": 51,
            "reasons": ["+38 digital design fit (title)"],
        }
        html = watcher.build_email_html({"Example Semiconductor": [job]})
        self.assertIn("HIGH PRIORITY", html)
        self.assertIn("Score 51", html)
        self.assertNotIn("Quant &mdash; New York", html)

    def test_email_caps_large_batches_without_losing_summary(self):
        jobs = []
        for i in range(30):
            jobs.append({
                "title": f"Software Intern {i}", "company": "Example",
                "content": "", "location": "", "url": f"https://example.com/{i}",
                "tier": "GOOD MATCH", "score": 30 + i, "reasons": ["technical fit"],
            })
        html = watcher.build_email_html({"Example": jobs}, max_roles=25)
        self.assertIn("top 25 of 30 new matches", html)
        self.assertIn("remaining 5 matches", html)
        self.assertEqual(html.count("https://example.com/"), 25)

    def test_fit_growth_model_labels_stretch_and_current_fit(self):
        profile = {
            "role_profiles": {
                "digital_design": {"demonstrated_fit": 25, "strategic_value": 100},
                "software": {"demonstrated_fit": 95, "strategic_value": 70},
            },
            "fit_growth_mix": {"demonstrated": 0.6, "strategic_growth": 0.4, "technical_points": 40},
            "role_keywords": {"digital_design": ["fpga"], "software": ["software"]},
        }
        fpga = watcher.score_job({"title": "FPGA Intern", "content": "", "location": ""}, profile)
        software = watcher.score_job({"title": "Software Intern", "content": "", "location": ""}, profile)
        self.assertEqual(fpga["match_type"], "HIGH-VALUE STRETCH")
        self.assertEqual(software["match_type"], "STRONG CURRENT FIT")
        self.assertGreater(software["score"], fpga["score"])

    def test_clearance_and_citizenship_are_distinguished(self):
        candidate = {
            "us_citizen": True,
            "holds_security_clearance": False,
            "open_to_clearance": True,
        }
        obtainable = watcher.assess_eligibility({
            "title": "Flight Software Intern",
            "content": "US citizenship required. Must be able to obtain and maintain a Secret clearance.",
        }, candidate)
        active = watcher.assess_eligibility({
            "title": "Embedded Intern",
            "content": "Candidate must possess an active Secret clearance.",
        }, candidate)
        self.assertEqual(obtainable["status"], "LIKELY ELIGIBLE")
        self.assertEqual(active["status"], "REVIEW ELIGIBILITY")

    def test_gpa_and_graduation_requirements_are_annotations(self):
        candidate = {
            "gpa": 3.2,
            "graduation_years_considered_relevant": [2030, 2031],
        }
        result = watcher.assess_eligibility({
            "title": "Architecture Intern 2029",
            "content": "Minimum GPA of 3.5. Applicants graduating in 2030 are eligible.",
        }, candidate)
        self.assertEqual(result["status"], "REVIEW ELIGIBILITY")
        self.assertTrue(any("3.5 GPA" in concern for concern in result["concerns"]))
        self.assertTrue(any("graduation-year" in note for note in result["notes"]))

    def test_private_config_overlay_merges_without_erasing_public_sections(self):
        public = {
            "filters": {"years": ["2029"], "priority_locations": []},
            "ranking": {"preferred_companies": [], "preferred_company_bonus": 10},
            "profile": {},
        }
        private = {
            "ranking": {"preferred_companies": ["Example Company"]},
            "profile": {"gpa": 3.0},
        }
        merged = watcher.merge_config(public, private)
        self.assertEqual(merged["filters"]["years"], ["2029"])
        self.assertEqual(merged["ranking"]["preferred_company_bonus"], 10)
        self.assertEqual(merged["ranking"]["preferred_companies"], ["Example Company"])
        self.assertEqual(merged["profile"]["gpa"], 3.0)


if __name__ == "__main__":
    unittest.main()

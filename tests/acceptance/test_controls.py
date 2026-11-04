"""The suite's own test: each fault planted in the SDK turns its cases red, and every judged case is turned red by some
fault, so a green run means something. Offline. Run: python -m unittest tests.acceptance.test_controls (a few minutes)."""
import concurrent.futures, json, os, shutil, socket, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CONTROL_JOBS = 4  # cases at a time within one control
PARALLEL_CONTROLS = 6
RUN_LIMIT = 300  # seconds a control's run may take

# A fault of faults.py -> the cells it must turn red, as (case, sdk). "*": each SDK the case has that is not cannot.
CONTROLS = {
    "key_on_every_request": [("routing_the_key_never_reaches_a_provider", "*"), ("no_harm_reflexer_busy", "*"),
                             ("kept_hooks_run_once_and_never_see_the_key_on_a_served_call", "*"), ("new_provider_busy_goes_straight", "acme"),
                             ("kept_hooks_run_once_and_never_see_the_key_on_a_fallback", "*"),
                             ("kept_the_key_stays_out_of_what_the_client_can_log", "*"), ("redirect_relayed_by_reflexer_goes_straight", "*")],
    "stock_pointed_at_reflexer": [("no_harm_reflexer_dead", "openai"), ("no_harm_reflexer_dead", "anthropic"), ("no_harm_reflexer_dead", "gemini"),
                                  ("no_harm_connection_reset", "openai"), ("no_harm_balancers_own_answer", "openai"), ("no_harm_reflexer_busy", "anthropic"),
                                  ("no_harm_reflexer_500", "openai"), ("no_harm_reflexer_429", "openai"), ("no_harm_answer_dropped", "openai"),
                                  ("no_harm_answer_not_http", "openai"), ("no_harm_certificate_not_trusted", "openai"),
                                  ("no_harm_provider_unreachable_from_reflexer", "openai"), ("no_harm_with_the_sdks_own_retries", "openai"),
                                  ("stream_reflexer_busy_goes_straight", "openai"),
                                  ("stream_reflexer_dead_goes_straight", "openai"), ("async_reflexer_busy_goes_straight", "openai"),
                                  ("async_reflexer_dead_goes_straight", "openai"), ("async_the_clients_timeout_holds_on_reflexers_leg", "openai"),
                                  ("async_redirect_goes_straight", "openai"),
                                  ("redirect_with_none_of_our_headers_goes_straight", "openai"), ("grace_a_key_expired_under_a_day_goes_straight_with_a_warning", "openai"),
                                  ("breaker_opens_on_a_failure", "openai"), ("breaker_busy_with_straight_goes_straight_uncounted", "openai"),
                                  ("timeout_the_clients_holds_on_reflexers_leg", "openai"), ("stall_reflexer_stalled_provider_at_six_tenths", "openai"),
                                  ("stall_every_call_answered_while_reflexer_stalls", "openai"), ("routing_the_body_is_the_clients_on_both_legs", "openai"),
                                  ("skip_goes_straight_and_its_flag_stays_here", "openai"), ("async_skip_goes_straight", "openai")],
    "stock": [("routing_a_message_call_reaches_reflexer_with_both_keys", "*"), ("routing_openai_responses_reach_reflexer", "openai"),
              ("routing_a_stream_call_reaches_reflexer", "*"), ("routing_a_router_is_named_as_the_upstream", "*"),
              ("routing_a_hosted_runner_is_named_as_the_upstream", "openai"), ("sampling_full_sends_all_to_reflexer", "*"),
              ("stream_served_through_reflexer", "*"), ("stream_arrives_event_by_event", "*"), ("async_stream_served", "*"),
              ("gzip_a_served_answer_with_its_fields", "*"), ("gzip_a_pass_through", "*"), ("bad_key_raises_before_anything_is_sent", "*"),
              ("kept_with_options_stays_on_reflexer", "*"), ("kept_with_raw_response", "*"), ("kept_the_clients_http_settings_on_both_legs", "*"),
              ("kept_a_cost_tool_patching_the_sdk_sees_one_call_and_our_cost", "*"),
              ("kept_a_cost_tool_patching_after_the_client_was_made_sees_it_too", "*"), ("kept_the_sdks_own_retries", "*"),
              ("kept_a_legacy_httpx_client", "openai"), ("kept_the_clients_own_transport_stays_open", "gemini"),
              ("kept_a_clients_attribute_named_like_ours_skips_nothing", "openai"), ("fields_a_pass_through_keeps_the_providers_cost", "*"),
              ("fields_a_pass_through_writes_no_cost", "gemini"), ("fields_leave_a_responses_bytes_untouched", "*"),
              ("new_provider_a_message_call_reaches_reflexer_with_its_fields", "acme"), ("fields_a_served_answers_model_shows_reflexer", "*"),
              ("fields_a_streams_usage_holds_the_price", "*"), ("fields_in_the_objects_dump", "*"), ("fields_on_a_streams_final_object", "*"),
              ("fields_an_object_with_no_room_keeps_its_answer", "*"),
              ("kept_proxy_https_proxy_takes_each_leg", "*"), ("kept_proxy_the_clients_explicit_proxy_takes_each_leg", "*"),
              ("kept_proxy_http_proxy_set_no_proxy_not", "*"), ("kept_a_providers_error_raises_the_sdks_own_class", "openai"),
              ("kept_a_raising_hook_is_the_clients_own", "openai"), ("kept_geminis_own_options_as_stock_takes_them", "gemini"),
              ("kept_the_clients_auth_on_both_legs", "*"), ("breaker_outage_trace_at_the_full_share", "openai"),
              ("breaker_outage_trace_at_the_one_percent_share", "openai")],
    "strips_the_price": [("fields_on_a_served_answer", "*"), ("async_served_with_fields", "*"),
                         ("new_provider_a_message_call_reaches_reflexer_with_its_fields", "acme"), ("gzip_a_served_answer_with_its_fields", "*")],
    "straight_dressed_as_served": [("fields_an_answer_that_went_straight_carries_none", "*")],
    "prices_a_pass_through": [("fields_a_pass_through_keeps_the_providers_cost", "*")],  # gemini's object takes no price: `stock` shows it
    "flag_not_read": [("skip_goes_straight_and_its_flag_stays_here", "*"), ("new_provider_skip_goes_straight", "acme"),
                      ("async_skip_goes_straight", "*"), ("stream_skip_goes_straight", "*")],
    "skip_sticks": [("skip_holds_for_one_call_only", "*")],
    "hop_loses_its_mark": [("redirect_on_a_straight_call_stays_straight", "*")],
    "share_ignored": [("sampling_none_sends_all_straight", "*"), ("sampling_a_tenth_sends_about_a_tenth", "*")],
    "routes_everything": [("routing_other_calls_go_straight", "*")],
    "routes_chat_only": [("routing_openai_responses_reach_reflexer", "openai")],
    "key_not_checked": [("bad_key_raises_before_anything_is_sent", "*")],
    "reaches_this_machine": [("routing_a_runner_on_this_machine_goes_straight", "*"), ("routing_a_plain_http_base_goes_straight", "*"),
                             ("kept_proxy_http_proxy_takes_a_plain_http_runner", "*")],
    "no_upstream": [("routing_a_router_is_named_as_the_upstream", "*"), ("routing_a_hosted_runner_is_named_as_the_upstream", "openai"),
                    ("routing_a_message_call_reaches_reflexer_with_both_keys", "azure")],
    "provider_key_dropped": [("routing_a_message_call_reaches_reflexer_with_both_keys", "*"),
                             ("new_provider_a_message_call_reaches_reflexer_with_its_fields", "acme")],
    "clients_headers_steer": [("routing_a_clients_own_reflexer_headers_never_steer_or_leave", "openai")],
    "trips_on_providers_status": [("breaker_a_providers_status_never_trips_it", "*"), ("kept_a_providers_error_raises_the_sdks_own_class", "openai")],
    "connection_counted": [("breaker_provider_unreachable_is_not_counted", "*")],
    "busy_with_straight_counted": [("breaker_busy_with_straight_goes_straight_uncounted", "*")],
    "redirect_is_an_answer": [("redirect_relayed_by_reflexer_goes_straight", "*"), ("async_redirect_goes_straight", "*")],
    "balancer_is_an_answer": [("no_harm_balancers_own_answer", "*"), ("redirect_with_none_of_our_headers_goes_straight", "*")],
    "busy_is_an_answer": [("no_harm_reflexer_busy", "*"), ("no_harm_reflexer_500", "*"), ("no_harm_reflexer_429", "*"),
                          ("new_provider_busy_goes_straight", "acme"), ("routing_the_body_is_the_clients_on_both_legs", "*")],
    "no_grace": [("grace_a_key_expired_under_a_day_goes_straight_with_a_warning", "*")],
    "expired_goes_straight": [("grace_a_key_expired_over_a_day_raises_to_the_client", "*")],
    "no_grace_warning": [("grace_a_key_expired_under_a_day_goes_straight_with_a_warning", "*")],
    "no_backoff": [("breaker_opens_on_a_failure", "*"), ("breaker_backs_off_doubling", "openai"), ("breaker_outage_trace_at_the_full_share", "openai")],
    "no_doubling": [("breaker_backs_off_doubling", "openai")],
    "no_jitter": [("breaker_jitters_so_clients_do_not_return_together", "openai")],
    "obeys_one": [("breaker_one_straight_header_is_not_obeyed", "*")],
    "never_obeys": [("breaker_two_straight_headers_are_obeyed_then_it_returns", "*")],
    "reads_any_straight": [("breaker_a_straight_header_it_does_not_know_is_ignored", "openai")],
    "counts_each_in_flight": [("breaker_counts_calls_in_flight_once", "openai")],
    "never_resets": [("breaker_an_answer_resets_the_backoff", "openai")],
    "timeout_dropped": [("timeout_the_clients_holds_on_reflexers_leg", "*"), ("async_the_clients_timeout_holds_on_reflexers_leg", "*"),
                        ("kept_with_options_timeout_holds", "*")],
    "timeout_halved": [("stall_slow_pass_through_at_seven_tenths", "*")],
    "body_changed": [("routing_the_body_is_the_clients_on_both_legs", "*")],
    "body_read_first": [("kept_a_body_not_read_goes_straight", "openai")],
    "body_not_read_counted": [("no_harm_a_body_not_read_goes_straight_and_counts_no_failure", "openai")],
    "streams_go_straight": [("routing_a_stream_call_reaches_reflexer", "*"), ("stream_served_through_reflexer", "*")],
    "reads_answers_whole": [("stream_arrives_event_by_event", "*"), ("no_harm_an_answer_cut_is_an_error_never_sent_twice", "*"),
                            ("no_harm_an_answer_broken_is_an_error_never_sent_twice", "*")],
    "edits_bytes": [("fields_leave_a_responses_bytes_untouched", "*")],
    "takes_no_gzip": [("gzip_a_served_answer_with_its_fields", "*"), ("gzip_a_pass_through", "*"), ("gzip_a_straight_answer", "*")],
    "cookie_for_anyone": [("kept_reflexers_cookie_never_reaches_the_provider", "openai")],
    "hooks_on_both_legs": [("kept_hooks_run_once_and_never_see_the_key_on_a_served_call", "*"),
                           ("kept_hooks_run_once_and_never_see_the_key_on_a_fallback", "*"), ("kept_a_raising_hook_is_the_clients_own", "*")],
    "closes_the_clients_own_http_client": [("kept_the_clients_own_transport_stays_open", "gemini")],
    "routes_the_clients_own_http_client": [("kept_a_shared_http_client_stays_the_clients", "openai")],
    "one_library_only": [("kept_a_legacy_httpx_client", "openai")],
    "tells_ours_by_a_name_a_client_may_use": [("kept_a_clients_attribute_named_like_ours_skips_nothing", "openai")],
    "every_gemini_argument_taken": [("kept_geminis_own_options_as_stock_takes_them", "gemini")],
    "drops_the_clients_http_client": [("kept_the_clients_http_settings_on_both_legs", "*"), ("kept_hooks_run_once_and_never_see_the_key_on_a_served_call", "*"),
                                      ("kept_a_raising_hook_is_the_clients_own", "*"), ("kept_the_clients_auth_on_both_legs", "*"),
                                      ("kept_proxy_the_clients_explicit_proxy_takes_each_leg", "*"), ("redirect_the_clients_setting_holds", "*")],
    "sets_its_own_retries": [("kept_the_sdks_own_retries", "*")],
    "not_the_sdks_class": [("kept_isinstance", "*")],
    "with_options_is_stock": [("kept_with_options_stays_on_reflexer", "*")],
    "calls_the_public_method_twice": [("kept_a_cost_tool_sees_one_call_on_a_fallback", "openai"),
                                      ("kept_a_cost_tool_patching_the_sdk_sees_one_call_and_our_cost", "openai"),
                                      ("kept_a_cost_tool_patching_after_the_client_was_made_sees_it_too", "openai")],
    "errors_of_our_own": [("kept_a_providers_error_raises_the_sdks_own_class", "openai")],
    "gemini_answer_dressed": [("fields_leave_geminis_object_what_it_was", "gemini")],
}
# Cases no fault turns red, and why each is kept.
NOT_JUDGED = {
    "measure_time_added_on_loopback": "records time added per call; no bound to hold",
    "measure_what_each_4xx_of_reflexers_does": "records which 4xx reach the client; nothing yet decides which should",
    "open_a_stalled_reflexer_told_from_a_slow_provider": "open: fails today, by a gap not built yet",
    "open_a_cut_answers_price_in_its_error": "open: fails today, by a gap not built yet",
    "open_bedrock": "cannot: no Bedrock client to run it on",
}


def run_suite(fault, only, work):
    """`run.py` on the cases named, with `fault` planted (None: the SDK as it is); its table, as JSON."""
    out = os.path.join(work, f"{fault}.json")
    command = [sys.executable, os.path.join(HERE, "run.py"), "--json", out, "--jobs", str(CONTROL_JOBS)]
    command += ["--fault", fault] if fault else []
    for name in only:
        command += ["--only", name]
    done = subprocess.run(command, capture_output=True, text=True, timeout=RUN_LIMIT)
    if done.returncode not in (0, 1) or not os.path.exists(out):  # 1: a cell failed, as a fault should make it
        raise AssertionError(f"run.py could not run {fault}: {done.stderr[-600:]}")
    with open(out) as results:
        return json.load(results)["cases"]


class Controls(unittest.TestCase):
    def test_each_fault_turns_its_cases_red_and_every_judged_case_is_turned_red(self):
        work = tempfile.mkdtemp(prefix="acceptance-controls-")
        self.addCleanup(shutil.rmtree, work, True)

        def run_one(fault):
            return fault, run_suite(fault, sorted({case for case, _ in CONTROLS[fault]}), work)

        seen_red, wrong = set(), []
        with concurrent.futures.ThreadPoolExecutor(PARALLEL_CONTROLS) as pool:
            for fault, rows in pool.map(run_one, CONTROLS):
                for case, sdk in CONTROLS[fault]:
                    matching = [row for row in rows if row["case"] == case and sdk in ("*", row["sdk"]) and row["status"] != "cannot"]
                    if not matching:
                        wrong.append(f"{fault}: {case}/{sdk} did not run")
                    for row in matching:
                        if row["status"] == "fail":
                            seen_red.add(case)
                        else:
                            wrong.append(f"{fault}: {row['case']}/{row['sdk']} is {row['status']}: {row['saw'][:200]}")
        self.assertEqual(wrong, [], "\n".join(wrong))
        import cases
        names = {case["name"] for case in cases.CASES}
        self.assertEqual(sorted(set(NOT_JUDGED) - names), [], "listed as not judged, and no such case")
        self.assertEqual(sorted(names - seen_red - set(NOT_JUDGED)), [], "cases no fault has turned red")

    def test_the_sdk_as_it_is_is_green_where_the_faults_are_red(self):
        """So that red is the fault's doing, not the case's."""
        work = tempfile.mkdtemp(prefix="acceptance-clean-")
        self.addCleanup(shutil.rmtree, work, True)
        rows = run_suite(None, ["routing_the_key_never", "no_harm_reflexer_dead", "fields_on_a_served"], work)
        self.assertEqual({row["status"] for row in rows}, {"pass"}, rows)

    def test_an_unknown_fault_is_refused(self):
        done = subprocess.run([sys.executable, os.path.join(HERE, "run.py"), "--fault", "made_up"], capture_output=True, text=True,
                              timeout=RUN_LIMIT)
        self.assertEqual(done.returncode, 2, done.stderr)


class Offline(unittest.TestCase):
    """The suite reaches its stand-ins by real names, and nothing beyond this machine."""

    def setUp(self):
        from harness import resolver
        self.resolver = resolver
        resolver.install()
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)
        resolver.add("api.openai.com", listener.getsockname()[1])
        self.addCleanup(resolver.hosts.clear)

    def test_a_name_of_the_suite_reaches_its_stand_in(self):
        socket.create_connection(("api.openai.com", 443), timeout=2).close()

    def test_any_other_name_fails_to_resolve(self):
        with self.assertRaises(socket.gaierror):
            socket.getaddrinfo("example.com", 443)

    def test_an_address_off_this_machine_refuses(self):
        with self.assertRaisesRegex(OSError, "offline"):
            socket.create_connection(("192.0.2.1", 443), timeout=2)


if __name__ == "__main__":
    unittest.main()

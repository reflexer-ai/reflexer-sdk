"""The suite's own test: each fault planted in the SDK turns its cases red, and every judged case is turned red by some
fault, so a green run means something. Offline. Run: python -m unittest tests.acceptance.test_controls (a few minutes)."""
import concurrent.futures, errno, json, os, re, shutil, socket, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import faults  # noqa: E402 the faults and conditions the controls plant
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
    "stock": [("routing_a_message_call_reaches_reflexer_with_both_keys", "*"), ("routing_openai_responses_reach_reflexer", "openai"), ("routing_azure_responses_reach_reflexer", "azure"),
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
    "flag_not_read": [("skip_goes_straight_and_its_flag_stays_here", "*"), ("litellm_skip_goes_straight_and_its_flag_stays_here", "*"), ("new_provider_skip_goes_straight", "acme"),
                      ("bedrock_skip_as_a_header_goes_straight", "litellm"),
                      ("async_skip_goes_straight", "*"), ("stream_skip_goes_straight", "*")],
    "skip_sticks": [("skip_holds_for_one_call_only", "*")],
    "hop_loses_its_mark": [("redirect_on_a_straight_call_stays_straight", "*")],
    "share_ignored": [("sampling_none_sends_all_straight", "*"), ("sampling_a_tenth_sends_about_a_tenth", "*")],
    "routes_everything": [("routing_other_calls_go_straight", "*")],
    "routes_chat_only": [("routing_openai_responses_reach_reflexer", "openai"), ("routing_azure_responses_reach_reflexer", "azure")],
    "key_not_checked": [("bad_key_raises_before_anything_is_sent", "*"), ("bad_key_on_bedrock_raises_before_anything_is_sent", "*")],
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
    "redirect_is_an_answer": [("redirect_relayed_by_reflexer_goes_straight", "*"), ("async_redirect_goes_straight", "*"),
                              ("redirect_on_bedrock_relayed_by_reflexer_goes_straight", "*")],
    "balancer_is_an_answer": [("no_harm_balancers_own_answer", "*"), ("redirect_with_none_of_our_headers_goes_straight", "*"),
                              ("no_harm_on_bedrock_balancers_own_answer", "*"), ("no_harm_on_bedrock_signed_balancers_own_answer", "*")],
    "busy_is_an_answer": [("no_harm_reflexer_busy", "*"), ("litellm_reflexer_busy_goes_straight", "*"), ("no_harm_reflexer_500", "*"), ("no_harm_reflexer_429", "*"),
                          ("no_harm_on_bedrock_reflexer_busy", "*"), ("no_harm_on_bedrock_a_key_bedrock_refuses_is_the_clients_error_sent_once", "*"), ("no_harm_on_bedrock_reflexer_500", "*"),
                          ("no_harm_on_bedrock_signed_reflexer_busy", "*"), ("no_harm_on_bedrock_signed_reflexer_500", "*"),
                          ("new_provider_busy_goes_straight", "acme"), ("routing_the_body_is_the_clients_on_both_legs", "*")],
    "no_grace": [("grace_a_key_expired_under_a_day_goes_straight_with_a_warning", "*")],
    "expired_goes_straight": [("grace_a_key_expired_over_a_day_raises_to_the_client", "*")],
    "no_grace_warning": [("grace_a_key_expired_under_a_day_goes_straight_with_a_warning", "*")],
    "no_backoff": [("breaker_opens_on_a_failure", "*"), ("breaker_backs_off_doubling", "openai"), ("breaker_outage_trace_at_the_full_share", "openai")],
    "no_doubling": [("breaker_backs_off_doubling", "openai")],
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
                            ("no_harm_on_bedrock_an_answer_cut_is_an_error_never_sent_twice", "anthropic-bedrock"),
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
    # Bedrock's
    "bedrock_stock": [("bedrock_a_keyed_call_reaches_reflexer_with_both_keys", "*"), ("bedrock_each_operation_is_served", "*"),
                      ("skip_on_bedrock_holds_for_one_call_only", "*"), ("bedrock_the_sdks_own_copy_stays_on_reflexer", "*"),
                      ("no_harm_on_bedrock_a_handshake_refused_once_is_tried_again", "*"), ("bedrock_a_closed_client_leaves_no_connection_to_reflexer", "*"),
                      ("bedrock_the_key_stays_out_of_what_the_client_can_log", "*")],
    "bedrock_streams_not_routed": [("bedrock_each_operation_is_served", "boto3"), ("bedrock_each_operation_is_served", "aiobotocore"),
                                   ("bedrock_each_operation_is_served", "litellm"), ("bedrock_each_operation_is_served", "anthropic-bedrock")],
    "bedrock_every_operation_routed": [("bedrock_count_tokens_goes_straight", "*")],
    "bedrock_signed_routed": [("bedrock_a_signed_mantle_call_never_reaches_reflexer_and_is_as_stock", "*")],
    "bedrock_signed_not_routed": [("bedrock_a_signed_call_reaches_reflexer_as_signed", "*"), ("bedrock_a_signed_calls_fallback_is_as_stock", "*")],
    "bedrock_not_signed_anew": [("bedrock_a_signed_calls_fallback_after_a_leg_past_the_window_is_taken", "*")],
    "bedrock_window_unbounded": [("bedrock_litellm_a_signed_calls_leg_is_cut_while_its_signature_holds", "litellm")],
    "bedrock_window_ignored": [("bedrock_litellm_a_signed_call_with_no_time_left_goes_straight", "litellm")],
    "bedrock_straight_changed": [("bedrock_a_signed_mantle_call_never_reaches_reflexer_and_is_as_stock", "*"),
                                 *[("bedrock_a_signed_calls_fallback_is_as_stock", lib) for lib in  # LiteLLM's: the shipped legs
                                   ("boto3", "aiobotocore", "langchain-aws", "strands", "pydantic-ai", "anthropic-bedrock")]],
    "bedrock_signed_over_handled_headers": [("bedrock_a_signed_calls_fallback_keeps_a_header_the_client_sets_as_it_signs", "boto3"),
                                            ("bedrock_a_signed_calls_fallback_keeps_a_header_the_client_sets_as_it_signs", "aiobotocore")],
    "bedrock_middleware_skip_ignored": [("bedrock_skip_on_a_signed_call_leaves_no_flag_and_the_signature_holds", "anthropic-bedrock")],
    "bedrock_skip_not_taken": [("bedrock_skip_as_an_argument_goes_straight", "*"), ("bedrock_skip_as_an_argument_on_a_signed_call_goes_straight", "*"),
                               ("bedrock_skip_on_a_signed_call_leaves_no_flag_and_the_signature_holds", "boto3")],
    "bedrock_share_ignored": [("sampling_on_bedrock_none_sends_all_straight", "*")],
    "bedrock_no_fallback": [("no_harm_on_bedrock_reflexer_dead", "*"), ("litellm_reflexer_dead_goes_straight", "*"), ("no_harm_on_bedrock_connection_reset", "*"), ("no_harm_on_bedrock_answer_dropped", "*"),
                            ("no_harm_on_bedrock_answer_not_http", "*"), ("no_harm_on_bedrock_certificate_not_trusted", "*"),
                            ("no_harm_on_bedrock_signed_reflexer_dead", "*"), ("no_harm_on_bedrock_signed_connection_reset", "*"),
                            ("no_harm_on_bedrock_signed_answer_dropped", "*"), ("no_harm_on_bedrock_signed_answer_not_http", "*"),
                            ("no_harm_on_bedrock_signed_certificate_not_trusted", "*"),
                            ("bedrock_the_clients_timeout_holds_on_reflexers_leg", "boto3"), ("bedrock_a_failure_opens_the_breaker", "*")],
    "bedrock_connection_is_an_answer": [("no_harm_on_bedrock_provider_unreachable_from_reflexer", "*"),
                                        ("no_harm_on_bedrock_signed_provider_unreachable_from_reflexer", "*")],
    "bedrock_cut_sent_again": [("no_harm_on_bedrock_an_answer_cut_is_an_error_never_sent_twice", "aiobotocore")],
    "bedrock_no_tls_retry": [("no_harm_on_bedrock_a_handshake_refused_once_is_tried_again", "*")],
    "bedrock_no_replay_guard": [("bedrock_a_replay_reflexer_does_not_take_never_reaches_bedrock", "*")],
    "bedrock_timeout_not_read": [("bedrock_litellm_async_the_clients_timeout_holds_on_reflexers_leg", "litellm")],
    "bedrock_handlers_answer_ignored": [("bedrock_a_handler_of_the_clients_that_answers_is_the_answer", "*")],
    "bedrock_copy_is_stock": [("bedrock_the_sdks_own_copy_stays_on_reflexer", "*")],
    "bedrock_key_on_the_clients_request": [("no_harm_on_bedrock_reflexer_busy", "boto3"), ("no_harm_on_bedrock_reflexer_busy", "aiobotocore")],
    "bedrock_own_session": [("bedrock_a_closed_client_leaves_no_connection_to_reflexer", "boto3")],
    "bedrock_first_loops_session": [("bedrock_aiobotocore_a_client_entered_in_a_second_event_loop_is_served", "aiobotocore")],
    "bedrock_route_logs_its_headers": [("bedrock_the_key_stays_out_of_what_the_client_can_log", "*")],
    # LiteLLM's line, on every provider
    "litellm_stock": [("litellm_a_call_reaches_reflexer_with_both_keys", "*"), ("litellm_each_way_is_served_async_and_streamed", "*"),
                      ("litellm_the_key_stays_out_of_what_the_client_can_log", "*")],
    "litellm_no_hook": [("litellm_each_way_is_served_async_and_streamed", "litellm-anthropic"),
                        ("litellm_each_way_is_served_async_and_streamed", "litellm-gemini")],
    "litellm_key_in_a_calls_metadata": [("litellm_the_key_stays_out_of_what_the_client_can_log", "*")],
}
# A slow machine's moment of faults.py's CONDITIONS -> the cases it must leave green: a busy machine turns none red.
SLOW_MACHINE = {
    "late_notice": ["timeout_the_clients_holds_on_reflexers_leg", "async_the_clients_timeout_holds_on_reflexers_leg",
                    "bedrock_the_clients_timeout_holds_on_reflexers_leg", "bedrock_litellm_async_the_clients_timeout_holds_on_reflexers_leg"],
    "a_stall_on_the_return": ["breaker_outage_trace_at_the_full_share", "breaker_outage_trace_at_the_one_percent_share"],
    "a_freeze": sorted(faults.FREEZES),  # each `steady` case, frozen where it breaks
}
def held_past_the_late_notice(row):
    import cases
    held = re.search(r"the client left reflexer after ([0-9.]+)s", row["saw"])
    return held is not None and float(held.group(1)) >= cases.CLIENT_TIMEOUT + cases.MARGIN / 4  # stock: the timeout itself


FIRED = {"late_notice": held_past_the_late_notice, "a_stall_on_the_return": lambda row: "tried again" in row["saw"],
         "a_freeze": lambda row: "tried again after the machine stalled" in row["saw"]}  # each came about
# Cases no fault turns red, and why each is kept.
NOT_JUDGED = {
    "measure_time_added_on_loopback": "records time added per call; no bound to hold",
    "measure_how_far_apart_clients_return": "records the spread of waits; a shared machine's noise is as large; tests/test_logic.py holds it",
    "measure_what_each_4xx_of_reflexers_does": "records which 4xx reach the client; nothing yet decides which should",
    "open_a_stalled_reflexer_told_from_a_slow_provider": "open: fails today, by a gap not built yet",
}


def run_suite(fault, only, work, condition=None, more=()):
    """`run.py` on the cases named, with `fault` planted (None: the SDK as it is), `condition`, and `more` of its
    arguments; its table, as JSON."""
    out = os.path.join(work, f"{fault}-{condition}-{'-'.join(more)}.json")
    command = [sys.executable, os.path.join(HERE, "run.py"), "--json", out, "--jobs", str(CONTROL_JOBS)]
    command += ["--fault", fault] if fault else []
    command += ["--condition", condition] if condition else []
    command += list(more)
    for name in only:
        command += ["--only", name]
    done = subprocess.run(command, capture_output=True, text=True, timeout=RUN_LIMIT)
    if done.returncode not in (0, 1) or not os.path.exists(out):  # 1: a cell failed, as a fault should make it
        raise AssertionError(f"run.py could not run {fault}, {condition}: {done.stderr[-600:]}")
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

    def test_each_steady_case_frozen_is_red_on_one_try(self):
        """So each case that discards a stalled try is seen to need it, and its freeze to land where it breaks it."""
        import cases
        self.assertEqual(sorted(case["name"] for case in cases.CASES if case["tries"] > 1), sorted(faults.FREEZES))
        work = tempfile.mkdtemp(prefix="acceptance-frozen-")
        self.addCleanup(shutil.rmtree, work, True)
        rows = [row for row in run_suite(None, sorted(faults.FREEZES), work, "a_freeze", ("--tries", "1")) if row["status"] != "cannot"]
        self.assertEqual(sorted({row["case"] for row in rows}), sorted(faults.FREEZES))
        green = [f"{row['case']}/{row['sdk']}: {row['saw'][:200]}" for row in rows if row["status"] != "fail"]
        self.assertEqual(green, [], "\n".join(green))

    def test_a_slow_machines_moment_turns_no_case_red(self):
        work = tempfile.mkdtemp(prefix="acceptance-slow-")
        self.addCleanup(shutil.rmtree, work, True)
        with concurrent.futures.ThreadPoolExecutor(PARALLEL_CONTROLS) as pool:
            ran = list(pool.map(lambda condition: (condition, run_suite(None, SLOW_MACHINE[condition], work, condition)), SLOW_MACHINE))
        red = [f"{condition}: {row['case']}/{row['sdk']} is {row['status']}: {row['saw'][:300]}"
               for condition, rows in ran for row in rows if row["status"] not in ("pass", "cannot")]
        self.assertEqual(red, [], "\n".join(red))
        for condition, rows in ran:
            self.assertEqual(sorted({row["case"] for row in rows}), sorted(SLOW_MACHINE[condition]), f"{condition}: not every case ran")
            for row in (row for row in rows if row["status"] == "pass"):
                self.assertTrue(FIRED[condition](row), f"{condition} did not come about in {row['case']}/{row['sdk']}: {row['saw'][:300]}")

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


class DeadStandIn(unittest.TestCase):
    """A dead stand-in refuses, and keeps its port: another case's stand-in, binding port 0 in a process of its own,
    would be handed a port let go, and get this case's calls, key included."""

    def setUp(self):
        from harness import standins
        self.standin = standins.Standin("runner")  # plain http: the port is the point, not TLS
        self.port = self.standin.port
        self.standin.set("dead")
        self.addCleanup(self.standin.set, "ok")

    def test_its_port_is_refused_to_another_bind(self):
        other = socket.socket()
        self.addCleanup(other.close)
        with self.assertRaises(OSError) as refused:
            other.bind(("127.0.0.1", self.port))
        self.assertEqual(refused.exception.errno, errno.EADDRINUSE)

    def test_its_port_is_never_handed_to_bind_0(self):
        with open("/proc/sys/net/ipv4/ip_local_port_range") as ports:
            low, high = map(int, ports.read().split())
        handed = 0
        for _ in range(high - low + 1):  # the size of the range bind(0) draws from
            with socket.socket() as other:
                other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as another case's stand-in binds
                other.bind(("127.0.0.1", 0))
                handed += other.getsockname()[1] == self.port
        self.assertEqual(handed, 0)

    def test_a_call_is_refused_and_it_comes_back_on_its_port(self):
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", self.port), timeout=2)
        self.standin.set("ok")
        socket.create_connection(("127.0.0.1", self.port), timeout=2).close()


class StalledStandIn(unittest.TestCase):
    """A stalled stand-in waits on any descriptor: a long test process's sockets pass `select()`'s FD_SETSIZE, past
    which it refuses one, and the call, cut, would go straight as from an outage."""
    FD_SETSIZE = 1024  # select()'s limit on Linux

    def test_its_wait_takes_a_descriptor_past_selects_limit(self):
        import resource
        from harness import standins
        past = 2 * self.FD_SETSIZE
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard != resource.RLIM_INFINITY and hard <= past:
            self.skipTest(f"this process may open {hard} descriptors, not past {past}")
        if soft != resource.RLIM_INFINITY and soft <= past:
            resource.setrlimit(resource.RLIMIT_NOFILE, (past + 1, hard))
            self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE, (soft, hard))
        ours, theirs = socket.socketpair()
        self.addCleanup(theirs.close)
        self.addCleanup(ours.close)
        os.dup2(ours.fileno(), past)
        high = socket.socket(fileno=past)
        self.addCleanup(high.close)
        theirs.sendall(b"x")
        self.assertEqual(standins.select.select([high], [], [], 2)[0], [high])

if __name__ == "__main__":
    unittest.main()

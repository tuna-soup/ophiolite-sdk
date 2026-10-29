"""E109's journey case list (strategy 6-7): every case of `ophiolite deliver`, each naming the slice that proves it.

A case list, not skipped tests: the SDK unit lane refuses a skipped case (tools/run-sdk-checks.py RequiredCases). A
case of a merged slice names the test that proves it (`test`, module::function); a case of a later slice names none
yet, and that slice replaces None with its test when it lands. test_deliver_contract.py checks the list's shape and
that every named test exists. Not collected by pytest (no test_ prefix)."""

SLICES = {0: 'Contract', 1: 'First delivery, confirmed or not sent', 2: 'Outcome unknown and reconciliation',
          3: 'A grid and vendor-shaped files'}

CASES = [
    # (slice, case id, what a person sees, test or None)
    (0, 'validate-send', 'procedures validate reads "Valid: Tops to team DB, version 1. It reads Well tops (CSV) and Team tops database and makes a delivery."',
     'test_deliver_contract.py::test_procedures_validate_names_the_destination_and_the_delivery'),
    (0, 'validate-two-systems', 'a send that names two systems is refused in words',
     'test_deliver_contract.py::test_a_send_with_two_systems_or_a_bad_reconcile_is_refused_in_words'),
    (0, 'run-send-later', 'procedures run of a send procedure still says it comes with a later release',
     'test_deliver_contract.py::test_running_a_send_procedure_locally_is_still_a_later_release'),
    (0, 'delivery-payload', 'the payload {delivery_id, state, items} is closed and bounded, by the same file as the server',
     'test_deliver_contract.py::test_the_delivery_payload_is_the_contract_s_and_closed'),
    (0, 'deliver-stub', 'ophiolite deliver --set-aside is passed to the client (slice 2 replaced the stub\'s refusal); the command writes no pending entry itself',
     'test_deliver_contract.py::test_deliver_passes_set_aside_to_the_client_and_reads_nothing_itself'),
    (1, 'confirmed', 'version 1, not the head, is written to the team\'s schema and the command says "Sent to Team tops database"',
     'gateway/test_deliver_journey.py::test_anna_delivers_version_one_not_the_head_to_the_team_schema'),
    (1, 'not-sent', 'a writer that refuses reads "Not sent to Team tops folder"',
     'test_deliver.py::test_a_writer_that_refuses_is_not_sent_and_its_reason_stays_here'),
    (1, 'refused-before-launch', 'a catalogue, trust, binding, settings or Windows refusal leaves no pending entry and no report',
     'test_deliver.py::test_a_refusal_before_launch_leaves_no_pending_record_no_call_and_no_report'),
    (1, 'never-relaunched', 'a pending attempt is never launched again; slice 2: it reads "Outcome unknown for ... It was not sent again."',
     'test_deliver.py::test_a_pending_attempt_is_never_launched_again'),
    (1, 'activity-and-story', 'Activity and the story read "Sent to ... by Tops to team DB on Anna\'s computer (reported)"',
     'gateway/test_deliver_journey.py::test_activity_and_the_story_say_sent_to_the_team_database'),
    (2, 'unknown', 'after the computer dies mid-delivery, the next deliver says "Outcome unknown", never a second send',
     'test_deliver.py::test_without_reconcile_the_outcome_stays_unknown_and_the_writer_is_not_run_again'),
    (2, 'reconcile-confirmed', 'reconcile finds the delivery id and reports confirmed, the writer having run once',
     'test_deliver.py::test_a_writer_killed_after_its_commit_is_reconciled_to_confirmed_and_ran_once'),
    (2, 'reconcile-not-sent', 'reconcile reports not sent only through the destination\'s tombstone',
     'test_deliver.py::test_absence_alone_stays_unknown_and_only_the_tombstone_says_not_sent'),
    (2, 'set-aside', '--set-aside keeps the outcome unknown on the record and clears it on this computer',
     'test_deliver.py::test_set_aside_records_unknown_clears_this_folder_and_a_new_delivery_may_start'),
    (3, 'grid-and-vendor-files', 'a grid and vendor-shaped files are delivered and read back with the same numbers', None),
]

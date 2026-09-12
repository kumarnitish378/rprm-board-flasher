"""Parser tests built from avrdude 8.0's documented and observed output.

The failure transcripts here were captured from the bundled
``avrdude 8.0-arduino.1`` binary; the success transcript is the one published in
the official 8.0 documentation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rprm_flasher.backends.avr.parser import AvrdudeParser, split_stream  # noqa: E402
from rprm_flasher.core.errors import explain  # noqa: E402
from rprm_flasher.core.events import Phase  # noqa: E402

BS = chr(92)

SUCCESS = (
    "Processing -U flash:w:diag.hex:i\n"
    "Reading 19278 bytes for flash from input file diag.hex\n"
    "Writing 19278 bytes to flash\n"
    "Writing | ################################################## | 100% 7.60 s\n"
    "Reading | ################################################## | 100% 6.81 s\n"
    "19278 bytes of flash verified\n"
    "\n"
    "Avrdude done.  Thank you.\n"
)

PORT_MISSING = (
    "Error: cannot open port \\\\.\\COM99: The system cannot find the file specified.\n"
    "\n"
    "Error: unable to open port COM99 for programmer stk500v1\n"
    "\n"
    "Avrdude done.  Thank you.\n"
)


def drain(parser: AvrdudeParser, text: str) -> list:
    events = list(parser.feed(text))
    events.extend(parser.finish())
    return events


class TestSplitting:
    def test_carriage_returns_become_separate_segments(self):
        # A redrawing progress bar arrives as one blob if CR is ignored.
        raw = "Writing | #     | 10% 1.0 s\rWriting | ##    | 20% 2.0 s\r"
        assert len(split_stream(raw)) == 2

    def test_mixed_line_endings(self):
        assert split_stream("a\r\nb\nc\rd") == ["a", "b", "c", "d"]

    def test_blank_segments_dropped(self):
        assert split_stream("\r\n\n  \n") == []


class TestSuccessRun:
    def test_reports_verified(self):
        parser = AvrdudeParser()
        drain(parser, SUCCESS)
        assert parser.verified
        assert parser.bytes_verified == 19278
        assert parser.bytes_written == 19278
        assert parser.errors == []

    def test_write_bar_and_verify_bar_are_distinguished(self):
        parser = AvrdudeParser()
        events = drain(parser, SUCCESS)
        phases = [e.phase for e in events if e.phase in (Phase.WRITING, Phase.VERIFYING)]
        # Both bars say 100%, but the second one is the verify pass.
        assert Phase.WRITING in phases
        assert Phase.VERIFYING in phases
        assert phases.index(Phase.WRITING) < phases.index(Phase.VERIFYING)

    def test_overall_progress_never_goes_backwards(self):
        parser = AvrdudeParser()
        events = drain(parser, SUCCESS)
        overalls = [e.overall for e in events]
        assert overalls == sorted(overalls), overalls

    def test_ends_at_one_hundred(self):
        parser = AvrdudeParser()
        events = drain(parser, SUCCESS)
        assert events[-1].overall == 100.0


class TestProgressMapping:
    def test_write_bar_tops_out_below_the_end(self):
        # A full write is only 80% of the job; verify still has to run.
        parser = AvrdudeParser()
        events = drain(
            parser,
            "Writing 100 bytes to flash\n"
            "Writing | ################## | 100% 1.0 s\n",
        )
        assert events[-1].phase is Phase.WRITING
        assert events[-1].overall == pytest.approx(80.0)

    def test_reading_bar_before_a_write_is_not_a_verify(self):
        parser = AvrdudeParser()
        events = drain(parser, "Reading | ####### | 50% 1.0 s\n")
        assert events[-1].phase is Phase.READING_INPUT

    def test_elapsed_seconds_captured(self):
        parser = AvrdudeParser()
        events = drain(parser, "Writing 10 bytes to flash\nWriting | ## | 20% 24.8 s\n")
        assert events[-1].elapsed == 24.8

    def test_avrdude_6_style_bar_without_the_space(self):
        parser = AvrdudeParser()
        events = drain(parser, "Writing 10 bytes to flash\nWriting | ## | 20% 0.05s\n")
        assert events[-1].phase is Phase.WRITING
        assert events[-1].phase_percent == 20.0


class TestChunking:
    def test_a_line_split_across_chunks_is_not_lost(self):
        parser = AvrdudeParser()
        events = list(parser.feed("19278 bytes of fl"))
        assert events == []
        events += list(parser.feed("ash verified\n"))
        events += list(parser.finish())
        assert parser.verified
        assert parser.bytes_verified == 19278

    def test_byte_at_a_time_gives_the_same_result(self):
        whole = AvrdudeParser()
        drain(whole, SUCCESS)

        dribbled = AvrdudeParser()
        for char in SUCCESS:
            list(dribbled.feed(char))
        list(dribbled.finish())

        assert dribbled.verified == whole.verified
        assert dribbled.bytes_verified == whole.bytes_verified


class TestSignature:
    def test_signature_and_chip_captured(self):
        parser = AvrdudeParser()
        drain(parser, "Device signature = 0x1e9801 (probably m2560)\n")
        assert parser.signature == "0x1e9801"
        assert parser.detected_chip == "m2560"

    def test_signature_without_a_chip_guess(self):
        parser = AvrdudeParser()
        drain(parser, "Device signature = 0x1e950f\n")
        assert parser.signature == "0x1e950f"
        assert parser.detected_chip is None


class TestFailures:
    def test_errors_collected(self):
        parser = AvrdudeParser()
        drain(parser, PORT_MISSING)
        assert len(parser.errors) == 2
        assert not parser.verified

    def test_done_line_is_not_a_success_signal(self):
        # avrdude prints "Avrdude done." after failures too.
        parser = AvrdudeParser()
        drain(parser, PORT_MISSING)
        assert "Avrdude done.  Thank you." in parser.lines
        assert parser.verified is False


class TestDiagnosis:
    def test_missing_port_names_the_port(self):
        friendly = explain(PORT_MISSING)
        assert "COM99" in friendly.title
        assert "refresh" in friendly.fix.lower()

    def test_isp_no_reply_mentions_the_capacitor(self):
        friendly = explain("Error: stk500_recv(): programmer is not responding")
        assert "programmer" in friendly.title.lower()
        assert "capacitor" in friendly.fix.lower()

    def test_signature_mismatch_quotes_the_signature(self):
        friendly = explain(
            "Error: Expected signature for ATmega2560 is 1E 98 01\n"
            "       Device signature = 0x1e950f, double check chip"
        )
        assert "0x1e950f" in friendly.fix

    def test_verification_error_names_the_address(self):
        friendly = explain("Error: verification error, first mismatch at byte 0x0200")
        assert "0x0200" in friendly.fix

    def test_unknown_output_falls_back_to_the_real_error(self):
        friendly = explain("Error: something nobody has a rule for yet\n")
        assert friendly.title == "Flashing failed"
        assert "something nobody has a rule for" in friendly.fix

    def test_empty_output_still_returns_advice(self):
        friendly = explain("")
        assert friendly.title
        assert friendly.fix


class TestMisdiagnosisRegressions:
    """avrdude prints a healthy "Device signature = ..." line on every good
    connection. An early version matched that line and reported the real cause
    of the failure as "wrong board selected", sending the operator to check
    wiring that was fine. Each case below must name its own cause."""

    HEALTHY_SIGNATURE = "Device signature = 0x1e9801 (probably m2560)\n"

    def test_verify_failure_is_not_called_a_wrong_board(self):
        friendly = explain(
            self.HEALTHY_SIGNATURE
            + "Error: verification error, first mismatch at byte 0x0200\n"
            "Error: verification error; content mismatch\n"
        )
        assert "read back wrong" in friendly.title
        assert "not the board" not in friendly.title

    def test_lost_port_is_not_called_a_wrong_board(self):
        # Built with chr(92) so the four real backslashes avrdude emits in
        # a Windows device path survive both the source and the regex.
        device = BS * 2 + '.' + BS + 'COM7'
        friendly = explain(
            self.HEALTHY_SIGNATURE
            + f'Error: cannot open port {device}: The system cannot find the file specified.'
        )
        assert 'COM7' in friendly.title
        assert 'not the board' not in friendly.title

    def test_a_real_mismatch_is_still_caught(self):
        friendly = explain(
            "Error: Expected signature for ATmega2560 is 1E 98 01\n"
            "       Device signature = 0x1e950f, double check chip\n"
        )
        assert "not the board you selected" in friendly.title
        assert "0x1e950f" in friendly.fix

    def test_a_healthy_signature_alone_diagnoses_nothing(self):
        from rprm_flasher.core.errors import diagnose

        assert diagnose(self.HEALTHY_SIGNATURE) is None

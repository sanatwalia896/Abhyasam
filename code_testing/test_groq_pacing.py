import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from groq_pacing import Pacer, ProviderRateLimitError, PacedGroq


class Clock:
    def __init__(self): self.now=0; self.waits=[]
    def time(self): return self.now
    def sleep(self, seconds): self.waits.append(seconds); self.now += seconds


class Limited(Exception):
    status_code=429
    def __init__(self, delay): self.response=SimpleNamespace(headers={'retry-after': str(delay)})


class PacingTests(unittest.TestCase):
    def pacer(self, clock): return Pacer(rpm=60,tpm=60000,clock=clock.time,sleep=clock.sleep)

    def test_successive_requests_do_not_wait_when_budget_remains(self):
        clock=Clock();pacer=self.pacer(clock)
        pacer.invoke(lambda:'first','prompt',100)
        pacer.invoke(lambda:'second','prompt',100)
        self.assertEqual(clock.waits,[])

    def test_actual_usage_does_not_charge_full_output_allowance(self):
        clock=Clock();pacer=Pacer(rpm=20,tpm=8000,clock=clock.time,sleep=clock.sleep)
        call=lambda:SimpleNamespace(usage_metadata={'input_tokens':600,'output_tokens':100,'total_tokens':700})
        for _ in range(8):pacer.invoke(call,'a'*2400,2048)
        self.assertEqual(clock.waits,[])
        self.assertEqual(sum(item[1] for item in pacer.history),5600)

    def test_waits_only_when_rolling_token_budget_is_used(self):
        clock=Clock();pacer=Pacer(rpm=60,tpm=1000,clock=clock.time,sleep=clock.sleep)
        call=lambda:SimpleNamespace(usage_metadata={'output_tokens':100,'total_tokens':800})
        pacer.invoke(call,'short',100)
        pacer.invoke(call,'x'*800,100)
        self.assertEqual(clock.waits,[60])

    def test_request_count_limit_is_enforced_even_for_small_responses(self):
        clock=Clock();pacer=Pacer(rpm=2,tpm=60000,clock=clock.time,sleep=clock.sleep)
        for _ in range(3):pacer.invoke(lambda:'ok','short',10)
        self.assertEqual(clock.waits,[60])

    def test_retry_after_is_respected(self):
        clock=Clock(); call=MagicMock(side_effect=[Limited(8),'success'])
        self.assertEqual(self.pacer(clock).invoke(call,'prompt',100),'success')
        self.assertGreaterEqual(sum(clock.waits),8)
        self.assertEqual(call.call_count,2)

    def test_daily_or_long_limit_returns_without_sleeping(self):
        clock=Clock();call=MagicMock(side_effect=Limited(3600))
        with self.assertRaises(ProviderRateLimitError) as result:self.pacer(clock).invoke(call,'prompt',100)
        self.assertGreaterEqual(result.exception.retry_after,3600)
        self.assertEqual(call.call_count,1)
        self.assertEqual(clock.waits,[])

    def test_retries_are_bounded(self):
        clock=Clock();call=MagicMock(side_effect=Limited(2))
        with self.assertRaises(ProviderRateLimitError):self.pacer(clock).invoke(call,'prompt',100)
        self.assertEqual(call.call_count,3)

    def test_other_errors_are_not_retried(self):
        call=MagicMock(side_effect=ValueError('invalid request'))
        with self.assertRaises(ValueError):self.pacer(Clock()).invoke(call,'prompt',100)
        self.assertEqual(call.call_count,1)

    def test_runnable_bind_passes_json_and_output_settings(self):
        client=SimpleNamespace(max_tokens=2048,invoke=MagicMock(return_value='result'))
        with patch('groq_pacing.get_pacer',return_value=self.pacer(Clock())):
            result=PacedGroq(client).bind(max_tokens=512,response_format={'type':'json_object'}).invoke('question')
        self.assertEqual(result,'result')
        self.assertEqual(client.invoke.call_args.kwargs['max_tokens'],512)


if __name__=='__main__':unittest.main()

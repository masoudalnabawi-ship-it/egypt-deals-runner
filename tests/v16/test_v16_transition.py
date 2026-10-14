import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))

class V16TransitionTests(unittest.TestCase):
    def test_cli_professional_dry_run_callable(self):
        import production_pipeline
        self.assertTrue(callable(production_pipeline.run_professional))
        result = production_pipeline.run_professional(send=False, discover_fn=lambda **kw: {'candidates': [], 'errors': []})
        self.assertEqual(result['discovered'], 0)

    def test_live_pipeline_no_v15_subprocess(self):
        import live_pipeline
        with patch.dict(sys.modules, {'fast_probe': type('Fake', (), {'probe_fast': staticmethod(lambda asin: iter([({'asin':asin},None,None),({'asin':asin},'image','digest')]))})}):
            self.assertEqual(list(live_pipeline.probe_one('B012345678')), [({'asin':'B012345678'},'image','digest')])

    def test_callback_edit_prompts_reply(self):
        from review_receiver import process_update
        events=[]
        cb={'id':'callback1','message':{'message_id':9},'data':'v16:edit:B012345678'}
        with patch('review_receiver.handle_callback',return_value={'status':'EDITING','asin':'B012345678','message':'ok'}), patch('review_receiver.review_chat',return_value='123'):
            process_update({'callback_query':cb},api=lambda method,payload:events.append((method,payload)))
        self.assertEqual([x[0] for x in events], ['sendMessage','answerCallbackQuery'])
        self.assertEqual(events[0][1]['reply_to_message_id'],9)

    def test_text_edit_updates_original_photo(self):
        from review_receiver import process_text_update
        events=[]
        msg={'message':{'from':{'id':7},'chat':{'id':123},'text':'نص جديد','reply_to_message':{'message_id':9}}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'V16_DEDUP_DB':str(Path(tmp)/'db.sqlite'),'V16_TELEGRAM_ADMIN_ID':'7','V16_TELEGRAM_REVIEW_CHAT_ID':'123'}):
            from review_store import set_state,get_state
            set_state('B012345678','editing')
            out=process_text_update(msg,resolve_asin=lambda mid:'B012345678',api=lambda method,payload:events.append((method,payload)))
            self.assertEqual(out['status'],'MESSAGE_SAVED')
            self.assertEqual(get_state('B012345678'),'pending')
            self.assertEqual(events[0][0],'editMessageCaption')
            self.assertEqual(events[0][1]['message_id'],9)

if __name__=='__main__': unittest.main()

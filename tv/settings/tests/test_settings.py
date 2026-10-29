import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lg_settings", ROOT / "settings.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class SelectionTests(unittest.TestCase):
    def test_default_profile_never_targets_core_agreements_or_services(self):
        ids = kit.selection("privacy")
        self.assertEqual(len(ids), 4)
        self.assertNotIn("netflix-preload-off", ids)
        self.assertNotIn("browser-preload-off", ids)

    def test_changes_need_explicit_apply_before_connecting(self):
        for action in ("apply", "rollback"):
            with self.assertRaises(ValueError):
                kit.request_for(argparse.Namespace(action=action, apply=False, profile="privacy", backup_id=None))

    def test_preloads_are_empty_until_owner_selects_apps(self):
        self.assertEqual(kit.selection("unused-preloads"), [])

    def test_doctor_maps_to_preview_only(self):
        request = kit.request_for(argparse.Namespace(action="doctor", apply=False, profile="privacy"))
        self.assertEqual(request["action"], "plan")
        self.assertNotIn("id", request)


@unittest.skipUnless(shutil.which("node"), "Node.js needed for mock Luna fixtures")
class RemoteTests(unittest.TestCase):
    def run_js(self, extra):
        source = (ROOT / "remote.js").read_text()
        fixture = """
var vm = require('vm'), calls = [], stored = {livePlus:'on'}, refuse=false;
var list = [{id:'netflix',isEnabled:true,requiredMemory:100},
            {id:'com.webos.app.home',isEnabled:true,extra:{keep:7}}];
var context = {module:{exports:{}}, require:function(name) {
 if(name==='fs')return {existsSync:function(){return false;}};
 if(name==='child_process')return {execFileSync:function(exe,args) {
  var uri=args[5], body=JSON.parse(args[6]); calls.push(uri);
  if(uri.indexOf('getConfigs')!==-1)return JSON.stringify({returnValue:true,configs:{'com.webos.service.preloadmanager.supportAppList':list}});
  if(uri.indexOf('setConfigs')!==-1){list=body.configs['com.webos.service.preloadmanager.supportAppList'];return '{"returnValue":true}';}
  if(uri.indexOf('getSystemSettings')!==-1)return JSON.stringify({returnValue:true,settings:stored});
  if(uri.indexOf('setSystemSettings')!==-1){if(refuse)return '{"returnValue":false}';Object.keys(body.settings).forEach(function(k){stored[k]=body.settings[k];});return '{"returnValue":true}';}
 }};
 throw Error('Unexpected module');
}};
context.require.main={}; vm.createContext(context);
""" + "vm.runInContext(" + json.dumps(source) + ",context);\n" + extra
        result = subprocess.run(["node", "-e", fixture], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_preview_unknown_never_writes(self):
        r = self.run_js("var p=context.plan(['live-plus-off','handsfree-voice-off']); console.log(JSON.stringify({plan:p,calls:calls}));")
        self.assertEqual(r["plan"][0]["status"], "change")
        self.assertEqual(r["plan"][1]["status"], "unsupported_or_unknown")
        self.assertFalse(any("setSystemSettings" in c for c in r["calls"]))

    def test_preload_preserves_unrelated_fields_and_entries(self):
        r = self.run_js("context.write('netflix-preload-off',false);console.log(JSON.stringify(list));")
        self.assertFalse(r[0]["isEnabled"])
        self.assertEqual(r[0]["requiredMemory"], 100)
        self.assertEqual(r[1], {"id": "com.webos.app.home", "isEnabled": True, "extra": {"keep": 7}})

    def test_rollback_does_not_overwrite_later_unknown_value(self):
        r = self.run_js("stored.livePlus='new-schema';var p=context.restore({operations:[{id:'live-plus-off',before:'on',after:'off'}]});console.log(JSON.stringify({plan:p,calls:calls}));")
        self.assertEqual(r["plan"][0]["status"], "restore_failed_or_unknown")
        self.assertFalse(any("setSystemSettings" in c for c in r["calls"]))

    def test_rollback_restores_original_value_and_readback(self):
        r = self.run_js("stored.livePlus='off';var p=context.restore({operations:[{id:'live-plus-off',before:'on',after:'off'}]});console.log(JSON.stringify({plan:p,value:stored.livePlus}));")
        self.assertEqual(r["plan"][0]["status"], "restored_verified")
        self.assertEqual(r["value"], "on")

    def test_refused_luna_write_is_not_success(self):
        r = self.run_js("refuse=true;var rejected=false;try{context.write('live-plus-off','off');}catch(e){rejected=true;}console.log(JSON.stringify({rejected:rejected,value:stored.livePlus}));")
        self.assertTrue(r["rejected"])
        self.assertEqual(r["value"], "on")

    def test_ambiguous_preload_does_not_write(self):
        r = self.run_js("list.push({id:'netflix',isEnabled:true});var p=context.plan(['netflix-preload-off']);console.log(JSON.stringify({plan:p,calls:calls}));")
        self.assertEqual(r["plan"][0]["status"], "unsupported_or_unknown")
        self.assertFalse(any("setConfigs" in c for c in r["calls"]))

    def test_backup_cannot_add_a_core_agreement(self):
        r = self.run_js("var rejected=false;try{context.validRecord({schema:1,id:'20261030T000000Z-abcdef01',operations:[{id:'generalTermsAllowed',before:true,after:false}]},'20261030T000000Z-abcdef01');}catch(e){rejected=true;}console.log(JSON.stringify({rejected:rejected}));")
        self.assertTrue(r["rejected"])


if __name__ == '__main__':
    unittest.main()

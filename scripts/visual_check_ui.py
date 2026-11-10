#!/usr/bin/env python3
"""Finite, isolated Playwright acceptance checks. No real files or commands run.

Run: python scripts/visual_check_ui.py [--output /tmp/chatbridge-ui-check]
The HTTP server is stopped when the checks finish. Screenshots are diagnostic.
"""
from __future__ import annotations
import argparse
import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MOCK = r"""
(() => {
  window.__calls = []; window.__events = []; window.__fits = [];
  window.__mockFile = 'const answer = 42;\nconsole.log(answer);\n';
  window.__mockRules = [{id:'r1',text:'I prefer small, readable changes.',enabled:true,builtin:true},{id:'r2',text:'I want actual results before a summary.',enabled:true,builtin:false}];
  window.__mockOn = true;
  const record = (method,args) => window.__calls.push({method,args});
  const event = value => setTimeout(() => window.__events.push(value),45);
  const api = {
    async bootstrap(){return {ok:true,version:'2.50.0',config:{full_access:true,custom_models:[],agent_rules:window.__mockRules,agent_rules_on:true,updates_seen:false},state:{active_chat_id:'c1',chats:[{id:'c1',title:'Workspace check',platform:'chatgpt',messages:[],project:{id:'p1',name:'sample-project',path:'/mock/project',branch:'main'}}]},status:{connected:false},provider:{enabled:false,port:8788,key:'test-key'}};},
    async drain_events(){const events=window.__events.splice(0);return {ok:true,events};},
    async state_save(state){record('state_save',[state]);return {ok:true};},
    async config_set(patch){record('config_set',[patch]);return {ok:true,config:patch};},
    async ibrowser_open(platform){record('ibrowser_open',[platform]);return {ok:true};},
    async ibrowser_close(){record('ibrowser_close',[]);return {ok:true};},
    async ibrowser_fit(...args){window.__fits.push(args);return {ok:true};},
    async browser_nav(...args){record('browser_nav',args);return {ok:true};},
    async browser_reinject(){record('browser_reinject',[]);return {ok:true};},
    async fs_tree(path=''){record('fs_tree',[path]);return {ok:true,root:'/mock/project',entries:[{name:'src',path:'src',type:'dir',children:[{name:'app.js',path:'src/app.js',type:'file',size:47}]},{name:'.git',path:'.git',type:'dir',hidden:true,children:[]}]};},
    async fs_read(path){record('fs_read',[path]);return {ok:true,path,content:window.__mockFile,lines:3,bytes:47};},
    async fs_write(path,content){record('fs_write',[path,content]);window.__mockFile=content;event({type:'fs_saved',id:'save1',path,ok:true});return {ok:true,id:'save1'};},
    async reveal_path(path){record('reveal_path',[path]);return {ok:true};},
    async agent_rules_get(){return {ok:true,rules:window.__mockRules,on:window.__mockOn};},
    async agent_rules_set(rules,on){record('agent_rules_set',[rules,on]);window.__mockRules=structuredClone(rules);window.__mockOn=on;return {ok:true,rules,on};},
    async agent_rules_reset(){window.__mockRules=[{id:'r1',text:'I restored my defaults.',enabled:true,builtin:true}];return {ok:true,rules:window.__mockRules,on:true};},
    async agent_rules_preview(text=''){record('agent_rules_preview',[text]);return {ok:true,text:[text,window.__mockOn?window.__mockRules.filter(r=>r.enabled).map(r=>r.text).join('\n\n'):''].filter(Boolean).join('\n\n')};},
    async send_message(...args){record('send_message',args);return {ok:true,request_id:'request-'+window.__calls.length};},
    async stop_message(...args){record('stop_message',args);return {ok:true};},
    async project_attach(path){record('project_attach',[path]);return {ok:true,project:{id:'p1',name:'sample-project',path:'/mock/project',branch:'main'}};},
    async terminal_run(cmd,cwd,timeout){record('terminal_run',[cmd,cwd,timeout]);event({type:'terminal_output',id:'term1',stream:'stdout',text:'\u001b[32mPASS <img src=x onerror=alert(1)>\u001b[0m\n'});event({type:'terminal_exit',id:'term1',exit:0,duration:0.1});return {ok:true,id:'term1'};},
    async terminal_kill(id){record('terminal_kill',[id]);return {ok:true};},
    async terminal_send(...args){record('terminal_send',args);return {ok:true};},
    async approval_response(...args){record('approval_response',args);return {ok:true};},
    async git_status(){return {ok:true,branch:'main',changes:[{path:'src/app.js',status:' M'}],branches:['main','feature']};},
    async git_action(action,args){record('git_action',[action,args]);event({type:'git_result',id:'git1',ok:true,result:{stdout:action==='diff'?'--- a/app.js\n+++ b/app.js\n+<script>unsafe()</script>':'OK',branches:['main','feature']}});return {ok:true,id:'git1'};},
    async list_web_chats(){return {ok:true,request_id:'list1'};},
    async read_web_chat(){return {ok:true,request_id:'read1'};},
    async new_web_chat(){return {ok:true,request_id:'new1'};}
  };
  window.__cbApi = new Proxy(api,{get(target,key){if(key in target)return target[key];return async (...args)=>{record(key,args);return {ok:false,error:'Mock method unavailable: '+String(key)};};}});
})();
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def check(page, output):
    results = []
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(MOCK)
    page.goto(check.url)
    page.wait_for_function('window.__cbUI && window.__cbUI.ready')
    page.wait_for_timeout(180)
    assert page.locator('#ibOpenBtn').is_visible()
    assert page.locator('#connectionText').inner_text() == 'NOT CONNECTED'
    assert page.locator('input[type=radio]').count() == 0
    results.append('visible browser header, honest connection, no radios')
    page.screenshot(path=str(output / 'workspace.png'))

    before = page.locator('#rightBlock').bounding_box()
    handle = page.locator('#rightSplitter').bounding_box()
    page.mouse.move(handle['x'] + handle['width']/2, handle['y'] + 140)
    page.mouse.down()
    page.mouse.move(handle['x'] + handle['width']/2 + 80, handle['y'] + 140, steps=10)
    page.mouse.up()
    page.wait_for_timeout(230)
    after = page.locator('#rightBlock').bounding_box()
    assert after['width'] < before['width'] - 60, (before, after)
    assert abs(after['x'] + after['width'] - 1440) < 2
    assert page.evaluate('window.__fits.length') > 2
    fit = page.evaluate('window.__fits.at(-1)')
    dock = page.locator('#ibDock').bounding_box()
    assert abs(fit[2] - dock['width']) < 2
    results.append('right drag narrows right dock; throttled native fit follows')

    browser_before = page.locator('#browserPane').bounding_box()['width']
    handle = page.locator('#browserSplitter').bounding_box()
    page.mouse.move(handle['x'] + 2, handle['y'] + 180)
    page.mouse.down()
    page.mouse.move(handle['x'] + 32, handle['y'] + 180, steps=6)
    page.mouse.up()
    assert page.locator('#browserPane').bounding_box()['width'] > browser_before + 15
    results.append('second physical divider resizes browser and utility')

    page.click('#hideBrowserBlock')
    assert not page.locator('#rightBlock').is_visible()
    assert page.locator('#ibOpenBtn').is_visible()
    page.click('#ibOpenBtn')
    assert page.locator('#rightBlock').is_visible()
    page.wait_for_timeout(130)
    assert page.evaluate('window.__fits.at(-1)[4]') is True
    results.append('header force-reveals persisted hidden dock')

    page.click('[data-tab=files]')
    page.wait_for_selector('#fileTree details')
    assert not page.locator('#fileTree details[data-path=".git"]').get_attribute('open')
    page.click('#fileTree details[data-path=src] > summary')
    page.click('#fileTree button[data-path="src/app.js"]')
    page.wait_for_function('document.getElementById("fileEditor").value.includes("answer")')
    page.fill('#fileEditor', 'const answer = 43;\n// edited by UI test\n')
    assert page.locator('#editorDirty').is_visible()
    page.locator('#fileEditor').press('Control+s')
    page.wait_for_function('window.__calls.some(c=>c.method==="fs_write")')
    page.wait_for_function('document.getElementById("editorDirty").hidden')
    saved = page.evaluate('window.__calls.find(c=>c.method==="fs_write").args')
    assert saved == ['src/app.js', 'const answer = 43;\n// edited by UI test\n'], saved
    assert 'File saved' in page.locator('#editorStatus').inner_text()
    results.append('file tree → editable FILE → dirty → Ctrl+S → fs_saved')

    page.click('#settingsBtn')
    page.click('[data-category=agent-rules]')
    page.locator('#agentRulesList textarea').first.fill('I prefer tests before changes. UI EDIT PROOF.')
    page.fill('#rulesPreviewInput','Please inspect my project.')
    page.click('#rulesPreviewBtn')
    page.wait_for_function('document.getElementById("rulesPreview").textContent.includes("UI EDIT PROOF")')
    assert 'Please inspect' in page.locator('#rulesPreview').inner_text()
    assert page.evaluate('window.__mockRules[0].text') == 'I prefer tests before changes. UI EDIT PROOF.'
    page.click('#addRuleBtn')
    page.locator('#agentRulesList textarea').last.fill('I want a concise explanation.')
    page.locator('#agentRulesList .rule-row').last.locator('button[role=switch]').click()
    page.click('#rulesPreviewBtn')
    page.wait_for_timeout(100)
    assert 'concise explanation' not in page.locator('#rulesPreview').inner_text()
    page.locator('#agentRulesList .rule-row').last.locator('button.danger-text').click()
    page.click('#agentRulesMaster')
    page.click('#rulesPreviewBtn')
    page.wait_for_timeout(100)
    assert page.locator('#rulesPreview').inner_text() == 'Please inspect my project.'
    page.click('#agentRulesMaster')
    page.click('#saveRulesBtn')
    results.append('rules edit/add/delete/toggle/master persist before API preview')

    page.click('[data-category=internal-browser]')
    assert page.locator('#browserSettings input[type=radio]').count() == 0
    assert not page.evaluate('window.__cbIbDockRect().visible')
    page.click('[data-category=appearance]')
    for theme in ('midnight','graphite','nord','forest','light','sepia'):
        page.select_option('#themeSelect',theme)
        assert page.get_attribute('html','data-theme') == theme
    for size in ('small','medium','large','extra-large'):
        page.select_option('#fontSizeSelect',size)
        assert page.get_attribute('html','data-font-size') == size
    page.select_option('#themeSelect','midnight')
    page.select_option('#fontSizeSelect','medium')
    page.click('[data-category=general]')
    page.select_option('#languageSelect','fa')
    page.wait_for_function('document.documentElement.dir === "rtl"')
    assert page.locator('#ibOpenBtn').is_visible()
    page.screenshot(path=str(output / 'settings-rtl.png'))
    page.click('#settingsCloseBtn')
    before = page.locator('#rightBlock').bounding_box()['width']
    handle = page.locator('#rightSplitter').bounding_box()
    page.mouse.move(handle['x'] + 2,handle['y'] + 130)
    page.mouse.down()
    page.mouse.move(handle['x'] + 52,handle['y'] + 130,steps=5)
    page.mouse.up()
    assert page.locator('#rightBlock').bounding_box()['width'] < before - 30
    results.append('six themes, four sizes, Persian RTL and right-drag geometry')
    page.click('#settingsBtn')
    page.select_option('#languageSelect','en')
    page.wait_for_function('document.documentElement.dir === "ltr"')
    page.click('#settingsCloseBtn')
    page.click('#resetLayoutBtn')

    raw = 'A safe answer.\n\n```chatbridge-tool-call\n{"tool":"run_command","args":{"cmd":"echo unsafe"}}\n```\n\n```js\nconst value = "<img src=x onerror=alert(1)>";\n```\n\n| Name | Value |\n| --- | --- |\n| safe | 42 |\n\n[Safe](https://example.com) [Unsafe](javascript:alert)\n<script>window.XSS = 1</script>'
    page.evaluate('(text)=>window.__cbUI.handleEvent({type:"assistant_response",request_id:"render1",chat_id:"c1",platform:"chatgpt",text,think:"My reasoning",operations:[{id:"op1",tool:"read_file",args:{path:"src/app.js"},status:"done",ok:true,result:{lines:3,content:"safe"}}]})',raw)
    assert 'chatbridge-tool-call' not in page.locator('#chatStream').inner_text()
    assert 'echo unsafe' not in page.locator('#chatStream').inner_text()
    assert page.locator('#chatStream pre code').count() == 1
    assert page.locator('#chatStream table').count() == 1
    assert page.locator('#chatStream a[href^="javascript:"]').count() == 0
    assert page.locator('#chatStream img, #chatStream script').count() == 0
    assert page.evaluate('window.XSS || null') is None
    page.locator('.operation-history summary').click()
    assert 'read' in page.locator('.operation-row').inner_text()
    assert page.locator('.thinking').count() == 1
    results.append('safe minimal Markdown, ordinary code/tables/links, thinking, no tool fence')

    page.evaluate('window.__cbUI.handleEvent({type:"tool_started",request_id:"render1",chat_id:"c1",id:"op2",tool:"run_command",verb:"run",target:"pytest",args:{cmd:"pytest"},status:"pending"})')
    assert page.locator('.operation-row[data-operation-id=op2]').is_visible()
    page.evaluate('window.__cbUI.handleEvent({type:"tool_finished",request_id:"render1",chat_id:"c1",id:"op2",tool:"run_command",verb:"run",target:"pytest",args:{cmd:"pytest"},status:"done",ok:true,result:{exit:0,stdout:"65 passed",duration:1}})')
    assert page.locator('.operation-history summary').inner_text().startswith('2')
    results.append('backend tool_started/tool_finished render as command history')
    page.evaluate('window.__cbUI.handleEvent({type:"assistant_response",request_id:"render1",chat_id:"c1",text:"Local work is complete.",continuation_pending:false})')

    page.click('[data-tab=terminal]')
    page.fill('#terminalCommand','echo test')
    page.click('#terminalForm button')
    page.wait_for_function('document.getElementById("terminalMeta").textContent.includes("Exit 0")')
    assert 'PASS <img' in page.locator('#terminalOutput').inner_text()
    assert page.locator('#terminalOutput img').count() == 0
    assert page.locator('#terminalOutput .ansi-green').count() > 0
    page.click('#terminalSendBtn')
    assert page.evaluate('window.__calls.some(c=>c.method==="terminal_send")')
    results.append('live terminal ANSI colors, output escaped, result send')

    page.evaluate('window.__cbUI.handleEvent({type:"approval_required",id:"approve1",tool:"write_file",summary:"Save app.js",detail:"<img src=x>",timeout:120})')
    assert page.locator('#approvalHost .approval-card').is_visible()
    assert page.locator('#approvalHost img').count() == 0
    page.locator('#approvalHost .primary').click()
    page.wait_for_function('window.__calls.some(c=>c.method==="approval_response"&&c.args[0]==="approve1"&&c.args[1]===true)')
    results.append('approval card and escaped details call approval_response')

    page.click('[data-tab=git]')
    page.wait_for_selector('.git-change')
    page.locator('.git-change button').filter(has_text='Diff').click()
    page.wait_for_function('document.getElementById("gitDiff").textContent.includes("unsafe")')
    assert page.locator('#gitDiff script').count() == 0
    count_before = page.evaluate('window.__calls.filter(c=>c.method==="git_action").length')
    page.locator('.git-change button').filter(has_text='Discard').click()
    assert page.locator('#confirmModal').is_visible()
    assert page.evaluate('window.__calls.filter(c=>c.method==="git_action").length') == count_before
    page.click('#confirmCancel')
    page.locator('.git-change button').filter(has_text='Discard').click()
    page.click('#confirmAccept')
    page.wait_for_function('window.__calls.some(c=>c.method==="git_action"&&c.args[0]==="discard")')
    results.append('Git diff escaped; destructive calls require explicit confirmation')

    for model in ('chatgpt','claude','zai','deepseek','gemini'):
        page.select_option('#modelSelect',model)
        page.fill('#composerInput',f'Mock prompt for {model}')
        page.locator('#composerInput').press('Enter')
        page.wait_for_function('(p)=>window.__calls.some(c=>c.method==="send_message"&&c.args[1]===p)',arg=model)
        request = page.evaluate('window.__calls.filter(c=>c.method==="send_message").at(-1)')
        assert request['args'][1:3] == [model,'c1']
        page.evaluate('(p)=>window.__cbUI.handleEvent({type:"platform_busy",platform:p,busy:true})',model)
        assert page.locator('#sendBtn').get_attribute('aria-label') == 'Stop generation'
        page.click('#sendBtn')
        assert page.evaluate('window.__calls.filter(c=>c.method==="stop_message").at(-1).args[1]') == model
        page.evaluate('(p)=>window.__cbUI.handleEvent({type:"assistant_response",request_id:"mock-"+p,chat_id:"c1",platform:p,text:"Captured mock response",operations:[]})',model)
    results.append('five web-model UI routes, send/stop mirror, mocked capture')
    page.evaluate('window.__cbUI.handleEvent({type:"assistant_response",request_id:"loop1",chat_id:"c1",text:"Running a local tool.",continuation_pending:true})')
    page.evaluate('window.__cbUI.handleEvent({type:"platform_busy",platform:"gemini",busy:false})')
    assert page.locator('#sendBtn').get_attribute('aria-label') == 'Stop generation'
    page.evaluate('window.__cbUI.handleEvent({type:"approval_required",request_id:"loop1",chat_id:"c1",id:"loop-approval",tool:"run_command",summary:"Pending local command"})')
    assert page.locator('#sendBtn').get_attribute('aria-label') == 'Stop generation'
    page.click('#sendBtn')
    assert page.evaluate('window.__calls.filter(c=>c.method==="stop_message").at(-1).args[0]') == 'loop1'
    page.evaluate('window.__cbUI.handleEvent({type:"approval_closed",id:"loop-approval"})')
    page.evaluate('window.__cbUI.handleEvent({type:"assistant_response",request_id:"loop1",chat_id:"c1",text:"Finished.",continuation_pending:false})')
    assert page.locator('#sendBtn').get_attribute('aria-label') == 'Send message'
    results.append('tool continuation and approval retain request Stop despite page idle; final answer releases it')
    page.click('[data-tab=browser]')
    page.screenshot(path=str(output / 'chat-and-browser.png'))
    assert not errors, f'JavaScript page errors: {errors}'
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='/tmp/chatbridge-ui-check')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(('127.0.0.1',0), handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    check.url = f'http://127.0.0.1:{server.server_port}/desktop/ui/index.html'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,args=['--no-sandbox'])
            context = browser.new_context(viewport={'width':1440,'height':940})
            page = context.new_page()
            results = check(page,output)
            preview = browser.new_context(viewport={'width':1440,'height':940})
            demo = preview.new_page()
            demo.goto(check.url)
            demo.wait_for_function('window.__cbUI && window.__cbUI.ready')
            assert demo.locator('#connectionText').inner_text() == 'NOT CONNECTED'
            demo.click('#ibOpenBtn')
            demo.wait_for_selector('.toast.error')
            assert 'Native bridge unavailable' in demo.locator('.toast.error').inner_text()
            assert demo.locator('#ibDockEmpty').is_visible()
            results.append('unmocked preview never claims a live native browser')
            report = {'ok':True,'checks':results,'page_errors':[],'screenshots':[str(file) for file in sorted(output.glob('*.png'))]}
            (output / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
            browser.close()
            for result in results:
                print('PASS:',result,flush=True)
            print(f'{len(results)} UI checks passed. Diagnostics: {output}',flush=True)
            return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    sys.exit(main())

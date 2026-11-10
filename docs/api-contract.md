# Implementation API contract — 2.50.0

All pywebview Api methods return JSON dictionaries `{ok: true, ...}` or `{ok:false,error: string}`. Async operations return `{ok:true,id}` and deliver completion through drain_events(). Events have a `type` key. The UI must not display raw tool fences; assistant events have `text` sanitized by the Python parser and optional `operations`.

## API methods

- bootstrap() -> {ok,version,config,state,platforms:[{id,name,home}],provider:{enabled,port,key},status}
- drain_events() -> {ok,events:[]}
- state_save(state) -> {ok}
- config_set(patch) -> {ok,config}
- send_message(text,platform,chat_id,attachment=null) -> {ok,request_id}
- stop_message(request_id,platform) -> {ok}
- new_web_chat(platform,resume='') -> {ok,request_id}
- list_web_chats(platform) -> {ok,request_id}; read_web_chat(platform,url,limit=40); load_older(platform,url)
- ibrowser_open(platform='chatgpt') / ibrowser_close() / ibrowser_fit(x,y,w,h,visible,cw,ch)
- browser_nav(action,url='') / browser_reinject() / browser_reset_profile()
- project_attach(path='') -> {ok,project}; empty path opens directory picker asynchronously
- chat_folder(name) -> {ok,project}
- fs_tree(path='') -> {ok,entries:[{name,path,type,size,children,hidden}],root}
- fs_read(path) -> {ok,path,content,lines,bytes} or {ok:false,error,binary,large}
- fs_write(path,content) -> {ok,id}; event fs_saved {path,ok,error?}
- reveal_path(path) -> {ok}
- terminal_run(cmd,cwd='',timeout=300) -> {ok,id}; terminal_output {id,stream,text}; terminal_exit {id,exit,duration}
- terminal_kill(id), terminal_send(id,platform,chat_id)
- git_status() -> {ok,branch,changes:[{path,status}],...}; git_action(action,args={}) -> {ok,id}; event git_result {id,ok,result,error?}. Actions diff,stage,unstage,commit,push,pull,discard,branches,checkout.
- approval_response(id,approved) -> {ok}
- agent_rules_get() -> {ok,rules,on}; agent_rules_set(rules,on=true) -> {ok,rules,on}; agent_rules_reset(); agent_rules_preview(text='') -> {ok,text}
- file_upload(name,mime,data_url,platform) / file_fetch(url,name,platform) / file_save(name,data_url) -> {ok,id}; file_ready {id,name,data_url,ok,error?}
- logs_get() -> {ok,lines}; logs_export() -> {ok,path}
- provider_set(enabled,port=8788) -> {ok,...}

## Module contracts

config.py: ConfigStore(base=None): get()->dict, update(patch)->dict, rules_get()->{rules,on}, rules_set(rules,on)->dict, rules_reset()->dict, rules_preview(text='',workspace=None)->str, load_state()->dict, save_state(state). config contains provider_key, custom_models, etc. Thread safe and atomic saves.

safety.py: Workspace(root): resolve(path)->Path, read_file(path,offset=0,limit=...)->dict, write_file(path,content=None,search=None,replace=None)->dict, list_dir(path='.',depth=1)->dict, search_files(query,path='.',regex=False,max=50)->dict. Denies paths outside root. Desktop tools may wrap this.

fstree.py: FileTree(root): tree(path='')->dict, read(path)->dict, write(path,content)->dict. Returns plain dictionaries; may raise ValueError/PermissionError for path errors, handled by Api. Configurable 2MB size cap.

terminal.py: TerminalManager(sink): run(cmd,cwd,timeout=300)->str id, kill(id)->bool, result(id)->dict. sink(event) callable. Background process with streaming stdout/stderr and process-tree cancellation.

gittools.py: GitTools(root): status()->dict, action(action,args=None)->dict.

project.py: ProjectRegistry(base): attach(path)->dict, list()->list. chatfolder.py: create_chat_folder(name,base=None)->dict with path/name/id.

audit.py: AuditLog(path): record(tool,args,ok,result=None,error=None), recent(limit=100)->list.

toolparse.py: parse_tool_calls(text,final=True)->list[{id,tool,args}], strip_tool_blocks(text)->str, has_unterminated(text)->bool. Parse errors use __parse_error__ args {reason,detail?}. Unknown healthy names are kept for steering by executor. Never dispatch an explicitly model-authored __parse_error__.

agent_cb.js: window.__CB__ entrypoints ping/meta/probe/send/enter/stop/baseline/snap + upload(name,mime,data_url), fetchFile(url), listChats(), readChat(limit), loadOlder(), navigate(url), approval(payload), drain(), dispose(). Async functions return JSON data. snap has count,text,busy,stage,think,think_active,url,title,ready,composer,files,limits. Agent performs DOM operations, driver owns capture state and Python parser.

## Trust and lifecycle additions

Remote `approval_response` packets can deny a request but cannot authorize local execution. Only the trusted local desktop Api.approval_response call grants approval. The RTL page overlay is a status/deny surface; approvalDismiss closes it after a desktop decision.

Driver assistant_response packets include `continuation_pending` while tool results and their subsequent capture are outstanding, so site-idle flips cannot hide the request's Stop control. `parsed_calls` is internal driver metadata used to keep operation IDs identical between final rendering and tool dispatch.

Provider user_message packets include `fresh:true`, which forces a new browser conversation before replaying the entire supplied transcript. Stop uses one WS dispatch and checks the current request owner immediately before native script evaluation; queued request cancellation never clicks Stop on another active turn.

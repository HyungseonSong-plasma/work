# FileRank: C
"""Versioned differential observations; execute as a script on a trusted snapshot."""

import contextlib
import io
import json
import os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app import cli
from app.commands import trigger as trigger_command
from github import delete, merge
from github import actions
from _snapshot_imports import library

transport = library("github")

def merge_operation(api, repository, ref, number, sha):
    return merge.MERGE.execute(merge.MergeOperation(api, repository, ref, number, sha))

R = "example/work"
ROOT = "repos/" + R
REF = "refs/heads/main"
SHA = "a" * 40
OTHER = "b" * 40
BRANCH = "feature/topic"
HEAD = "refs/heads/" + BRANCH
REPO = {"id":1,"default_branch":"main"}
RESULTS = {}

def pr(merged=False):
    return {"state":"closed" if merged else "open","merged":merged,"draft":False,
            "base":{"ref":"main","repo":{"full_name":R}},
            "head":{"sha":SHA,"ref":BRANCH,"repo":{"full_name":R}}}

def record(name, operation, trace):
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            result={"value":operation()}
        except SystemExit as error:
            result={"exit":error.code}
        except (ValueError,KeyError,TypeError,OSError) as error:
            result={"error":type(error).__name__,"message":str(error)}
    result.update(stdout=out.getvalue(),stderr=err.getvalue(),
                  trace=[(item[0],item.args,item.kwargs) for item in trace.mock_calls])
    if name in RESULTS:
        raise ValueError(f"Duplicate observation: {name}")
    RESULTS[name]=result

for name in ("valid","number","sha","ref","draft","closed","merged","base","repository","head","unconfirmed","bad_result_sha"):
    p=pr()
    n,sha,ref=7,SHA,REF
    reply={"merged":True,"sha":OTHER}
    if name=="number": n=True
    if name=="sha": sha="bad"
    if name=="ref": ref="refs/heads/other"
    if name=="draft": p["draft"]=True
    if name=="closed": p["state"]="closed"
    if name=="merged": p["merged"]=True
    if name=="base": p["base"]["ref"]="other"
    if name=="repository": p["base"]["repo"]["full_name"]="other/work"
    if name=="head": p["head"]["sha"]=OTHER
    if name=="unconfirmed": reply["merged"]=False
    if name=="bad_result_sha": reply["sha"]="bad"
    trace=Mock()
    api=Mock(side_effect=[deepcopy(REPO),p,reply])
    trace.attach_mock(api,"api")
    record("merge:"+name,lambda:merge_operation(api,R,ref,n,sha),trace)

for name in ("valid","wrong_ref","open","unmerged","head_changed","fork","missing_repo","reserved",
             "absent","git_changed","protected","api_changed","head_in_use","base_in_use",
             "unknown_repo","fork_reference","invalid_page","lease_failure"):
    p=pr(True)
    ref=REF
    details={"protected":False,"commit":{"sha":SHA}}
    status=0
    stdout=f"{SHA}\t{HEAD}\n"
    unrelated={"head":{"ref":"unrelated","repo":{"full_name":R}},
               "base":{"ref":"main","repo":{"full_name":R}}}
    page=[deepcopy(unrelated)]
    if name=="wrong_ref": ref="refs/heads/other"
    if name=="open": p["state"]="open"
    if name=="unmerged": p["merged"]=False
    if name=="head_changed": p["head"]["sha"]=OTHER
    if name=="fork": p["head"]["repo"]={"full_name":"other/work"}
    if name=="missing_repo": p["head"]["repo"]=None
    if name=="reserved": p["head"]["ref"]="master"
    if name=="absent": status=2
    if name=="git_changed": stdout=f"{OTHER}\t{HEAD}\n"
    if name=="protected": details["protected"]=True
    if name=="api_changed": details["commit"]["sha"]=OTHER
    if name in ("head_in_use","base_in_use","unknown_repo","fork_reference"):
        side="base" if name=="base_in_use" else "head"
        repo=None if name=="unknown_repo" else {"full_name":"other/work" if name=="fork_reference" else R}
        page[0][side]={"ref":BRANCH,"repo":repo}
    if name=="invalid_page": page={}
    trace=Mock()
    api=Mock(side_effect=[deepcopy(REPO),p,details,[unrelated]*100,page])
    git=Mock(side_effect=[None,SimpleNamespace(returncode=status,stdout=stdout),
                          ValueError("Git push failed (exit 1).") if name=="lease_failure" else None])
    trace.attach_mock(api,"api")
    trace.attach_mock(git,"git")
    record("branch:"+name,lambda:delete.delete_branch(api,git,R,ref,"7",SHA,"remote"),trace)

def run(i):
    return {"id":i,"repository":{"id":1,"full_name":R},"head_sha":SHA,
            "run_attempt":1,"status":"completed","path":".github/workflows/disposable.yml"}
def target(i):
    return {"run_id":i,"expected_head_sha":SHA,"expected_run_attempt":1}

for name in ("batch","single","preflight","fresh_metadata","delete_failure","report_failure",
             "wrong_ref","current","retained","older_success","invalid_listing","changed_attempt"):
    first,second,third=run(12),run(14),run(15)
    targets=[target(12),target(14),target(15)]
    ref,current=REF,13
    responses=[deepcopy(REPO),first,second,third,first,second,third]
    if name=="single": targets=[target(12)];responses=[deepcopy(REPO),first,first]
    if name=="preflight": responses[3]=dict(third,status="in_progress")
    if name=="fresh_metadata": responses[5]=dict(second,extra="changed")
    if name=="changed_attempt": responses[5]=dict(second,run_attempt=2)
    if name=="wrong_ref": ref="refs/heads/other"
    if name=="current": current=14
    if name in ("retained","older_success","invalid_listing"):
        targets=[target(12)]
        first=dict(first,path=".github/workflows/trigger.yml",workflow_id=7,
                   conclusion="success",created_at="2026-11-27T10:00:00Z")
        newer=dict(first,id=20,created_at="2026-11-27T11:00:00Z")
        listing=[first] if name=="retained" else [newer,first]
        if name=="invalid_listing": listing=[first,newer]
        listing={"total_count":len(listing),"workflow_runs":listing}
        responses=[deepcopy(REPO),first,listing,first,listing]
    trace=Mock()
    api=Mock(side_effect=responses)
    remove=Mock(side_effect=[None,ValueError("delete failed")] if name=="delete_failure" else None)
    report=Mock(side_effect=ValueError("report failed") if name=="report_failure" else None)
    for label,mock in (("api",api),("remove",remove),("report",report)):
        trace.attach_mock(mock,label)
    if name=="single":
        operation=lambda:actions.delete_actions_run(api,remove,R,ref,12,SHA,1,current)
    else:
        operation=lambda:actions.delete_actions_batch(api,remove,R,ref,targets,current,report=report)
    record("actions:"+name,operation,trace)

def event(body):
    return {"action":"created","repository":{"full_name":R,"default_branch":"main","owner":{"id":1}},
            "comment":{"id":12,"user":{"id":1},"author_association":"OWNER","created_at":"now",
                       "updated_at":"now","body":"/execute "+json.dumps(body)},
            "sender":{"id":1},"issue":{"number":7,"pull_request":{}}}
for name in ("merge","branch","serial","reverse","unknown","queue","actions_single","actions_batch",
             "actions_mixed","actions_edited","wrong_actor","wrong_repo","wrong_ref","invalid_id",
             "invalid_sha","invalid_queue"):
    body={"execution":"pr_merge.py","expected_head_sha":SHA}
    if name=="branch": body["execution"]="branch_delete.py"
    if name=="serial": body["execution"]="pr_merge.py - branch_delete.py"
    if name=="reverse": body["execution"]="branch_delete.py - pr_merge.py"
    if name=="unknown": body["execution"]="unknown.py"
    if name=="queue": body["queue_comment_id"]=9
    if name=="invalid_queue": body["queue_comment_id"]=True
    if name=="invalid_sha": body["expected_head_sha"]="bad"
    if name.startswith("actions_"):
        body={"execution":"delete actions",**target(12)}
    if name=="actions_batch": body={"execution":"delete actions","runs":[target(12),target(14)]}
    if name=="actions_mixed": body["runs"]=[target(12)]
    e=event(body)
    repo,ref=R,REF
    if name=="actions_edited": e["comment"]["updated_at"]="later"
    if name=="wrong_actor": e["sender"]["id"]=2
    if name=="wrong_repo": repo="other/work"
    if name=="wrong_ref": ref="refs/heads/other"
    if name=="invalid_id": e["comment"]["id"]=True
    trace=Mock()
    dispatch=Mock()
    trace.attach_mock(dispatch,"dispatch")
    record("route:"+name,lambda:trigger_command.dispatch_request(e,repo,ref,dispatch),trace)

def transport_request(method, endpoint, payload, send):
    return transport.GitHubClient(send).request(method, endpoint, payload)
def transport_dispatch(repository, workflow, payload, send):
    return transport.GitHubClient(send).dispatch(repository, workflow, payload)
def transport_delete(endpoint, send):
    return transport.GitHubClient(send).delete(endpoint)

for method,status in (("GET",200),("PUT",200),("POST",200),("POST",204),("POST",202),
                      ("DELETE",204),("DELETE",200),("DELETE",202),
                      ("POST","timeout"),("DELETE","timeout"),("PUT","bad_json")):
    trace=Mock()
    def send(request,timeout):
        trace.request(request.get_method(),request.full_url,dict(request.header_items()),
                      None if request.data is None else request.data.decode(),timeout)
        if status=="timeout":
            raise TimeoutError("ambiguous response")
        response=io.BytesIO(b"invalid" if status=="bad_json" else b'{"confirmed": true}')
        response.status=status
        return contextlib.nullcontext(response)
    if method=="POST":
        operation=lambda:transport_dispatch(R,"single_run.yml",{"ref":"main","inputs":{"request_id":"comment-12"}},send=send)
    elif method=="DELETE":
        operation=lambda:transport_delete(ROOT+"/actions/runs/12",send=send)
    else:
        operation=lambda:transport_request(method,ROOT,None if method=="GET" else {"sha":SHA},send=send)
    with patch.dict(os.environ,{"GITHUB_API_URL":"https://api.example.test/","GH_TOKEN":"fixture"},clear=True):
        record(f"transport:{method}:{status}",operation,trace)

for args in ([],["trigger"],["execute"],["merge"],["delete"],["test"]):
    record("cli:help:"+"/".join(args),lambda:cli.main(args+["--help"]),Mock())
for args in ([],["unknown"],["execute"],["delete","unknown"],["execute","--serial-stage","3"]):
    record("cli:invalid:"+"/".join(args),lambda:cli.main(args),Mock())
_command = library("command")
Command, CommandPlan = _command.Command, _command.CommandPlan
local_plan, validate_command = _command.local_plan, _command.validate_command
from app.wiring import register as register_command, configured_commands, COMMANDS, resolve_execution
registry_module = "app.wiring"
from tests import suites
TestSuite = library("testing").TestSuite
from tests.wiring import register as register_suite, build_suite, SUITES
WorkflowRegistry = transport.WorkflowRegistry

class Sample(Command):
    help = "fixture"
    plan = local_plan(lambda ctx, args: 7)
class BadCommand(Sample):
    @staticmethod
    def execute(args): return 0
class SampleSuite(TestSuite):
    def test_one(self):
        def check(ctx):
            pass
        self.run_contract(check=check)
class BadSuite(TestSuite):
    def test_one(self):
        self.assertTrue(True)

for name,key,value in (("valid","sample",Sample),("duplicate","trigger",object),
                       ("invalid_name","-bad",Sample),("invalid_type","bad",object),
                       ("override","bad",BadCommand)):
    with patch.dict(COMMANDS):
        record("command_registry:"+name,lambda:(register_command(key)(value), list(COMMANDS))[1],Mock())
for name,names in (("ordered",("merge","trigger")),("subset",("test",)),("missing",("unknown",))):
    with patch(registry_module+".load_names",return_value=names):
        record("command_registry:"+name,lambda:list(configured_commands()),Mock())
for name,key,value in (("valid","sample",SampleSuite),("registration_duplicate","registry",object),
                       ("invalid_name","",SampleSuite),("invalid_type","bad",object)):
    with patch.dict(SUITES):
        record("suite_registry:"+name,lambda:(register_suite(key)(value),list(SUITES))[1],Mock())
for name,names,registered in (("ordered",("second","first"),{"first":SampleSuite,"second":SampleSuite}),
                               ("missing",("first",),{"first":SampleSuite,"second":SampleSuite}),
                               ("duplicate",("first","first"),{"first":SampleSuite}),
                               ("empty",(),{}),("unknown",("missing",),{"first":SampleSuite}),
                               ("unstructured",("registry",),{"registry":BadSuite})):
    record("suite_registry:"+name,lambda:build_suite(names=names,registered=registered).countTestCases(),Mock())
for name,chain,workflow in (("valid",("merge.py",),"single.yml"),("duplicate_key",("merge.py","merge.py"),"single.yml"),
                             ("invalid_key","merge.py","single.yml"),("invalid_file",("merge.py",),"../single.yml"),
                             ("duplicate_route",("merge.py",),"../single.yml"),("unknown",("unknown.py",),None)):
    routes=WorkflowRegistry()
    if name=="duplicate_route": routes.register(("merge.py",),"single.yml")
    def route_operation():
        if workflow is not None: routes.register(chain,workflow)
        return routes.resolve(chain)
    record("workflow_registry:"+name,route_operation,Mock())
for name,callback in (("valid",lambda x:0),("none",None),("wrong_arity",lambda x,y:0)):
    record("callback:"+name,lambda:(CommandPlan(lambda args:None,lambda ctx,args:ctx,
                                               callback if name!="valid" else lambda ctx,args:0), "ok")[1],Mock())
    suite=TestSuite()
    record("runner:"+name,lambda:suite.run_contract(check=callback),Mock())
for name,status,has_report,failure in (
    ("status_report",True,True,None),("zero_report",False,True,None),
    ("status_no_report",True,False,None),("zero_no_report",False,False,None),
    ("prepare_failure",True,True,"prepare"),("validate_failure",True,True,"validate"),
    ("action_failure",True,True,"action"),("report_failure",True,True,"report")):
    trace=Mock()
    callbacks={}
    for stage,value in (("prepare","prepared"),("validate","validated"),("action",7),("report",None)):
        callback=Mock(return_value=value,side_effect=ValueError(stage) if stage==failure else None)
        trace.attach_mock(callback,stage)
        callbacks[stage]=callback
    class Lifecycle(Command):
        help="lifecycle probe"
        plan=CommandPlan(callbacks["prepare"],callbacks["validate"],callbacks["action"],
                         callbacks["report"] if has_report else None,status)
    record("command_lifecycle:"+name,lambda:Lifecycle.execute({"argument":"fixture"}),trace)
class Targeted(Command):
    help="target probe"
    targets=(("branch",local_plan(lambda ctx,args:7)),)
record("command_lifecycle:unknown_target",lambda:Targeted.execute(SimpleNamespace(target="invalid")),Mock())
_workflow = library("workflow")
PRContext, Context = _workflow.PRContext, _workflow.Context
from github.actions import ActionsContext
def make_pr(execution,env):
    return PRContext(execution,env=env,resolve=resolve_execution)
env0={"GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_RUN_ATTEMPT":"1",
      "GITHUB_REPOSITORY":R,"GITHUB_REF":REF,"EXECUTION_INPUTS":json.dumps({"pr_number":7,"expected_head_sha":SHA}),
      "GITHUB_SERVER_URL":"https://github.com","GITHUB_ACTOR_ID":"1",
      "GITHUB_WORKFLOW_REF":R+"/.github/workflows/actions_delete.yml@"+REF,"GITHUB_RUN_ID":"13",
      "GITHUB_API_URL":"https://api.github.com"}
for name,execution,changes in (
    ("valid","pr_merge.py",{}),("wrong_event","pr_merge.py",{"GITHUB_EVENT_NAME":"issue_comment"}),
    ("rerun","pr_merge.py",{"GITHUB_RUN_ATTEMPT":"2"}),("unknown","unknown.py",{}),
    ("invalid_parameters","pr_merge.py",{"EXECUTION_INPUTS":"{}"}),
    ("bad_sha","pr_merge.py",{"EXECUTION_INPUTS":json.dumps({"pr_number":7,"expected_head_sha":"bad"})}),
    ("bad_number","pr_merge.py",{"EXECUTION_INPUTS":json.dumps({"pr_number":"07","expected_head_sha":SHA})})):
    def review_context():
        context=make_pr(execution,dict(env0,**changes)).validate()
        return [context.number,context.sha,context.repository,context.ref,context.remote]
    record("pr_context:"+name,review_context,Mock())
for name in ("owner_single","owner_batch","wrong_actor","wrong_workflow","sender_mismatch","bot_without_approval",
             "bot_approved_batch","edited_approval","different_inputs","mixed_inputs","rerun","wrong_ref"):
    env=dict(env0)
    event={"repository":{"full_name":R,"default_branch":"main","owner":{"id":1}},"sender":{"id":1}}
    target={"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}
    args=SimpleNamespace(runs="",run_id=12,expected_head_sha=SHA,expected_run_attempt=1,request_id="",source_pr="")
    comment={"id":12,"user":{"id":1},"author_association":"OWNER","created_at":"now","updated_at":"now",
             "issue_url":"https://api.github.com/repos/"+R+"/issues/7",
             "body":"/execute "+json.dumps({"execution":"delete actions","runs":[target]})}
    approved_pr={"number":7,"base":{"repo":{"full_name":R}}}
    if name in ("owner_batch","bot_approved_batch","edited_approval"):
        args.runs=json.dumps([target])
        args.run_id=args.expected_head_sha=args.expected_run_attempt=None
    if name=="wrong_actor": env["GITHUB_ACTOR_ID"]="2"; event["sender"]["id"]=2
    if name=="wrong_workflow": env["GITHUB_WORKFLOW_REF"]="other"
    if name=="sender_mismatch": event["sender"]["id"]=2
    if name in ("bot_without_approval","bot_approved_batch","edited_approval","different_inputs"):
        env["GITHUB_ACTOR_ID"]="41898282"
        event["sender"]={"id":41898282,"login":"github-actions[bot]"}
    if name in ("bot_approved_batch","edited_approval","different_inputs"):
        args.request_id="comment-12"; args.source_pr="7"
    if name=="edited_approval": comment["updated_at"]="later"
    if name=="mixed_inputs": args.runs=json.dumps([target])
    if name=="rerun": env["GITHUB_RUN_ATTEMPT"]="2"
    if name=="wrong_ref":
        env["GITHUB_REF"]="refs/heads/other"
        env["GITHUB_WORKFLOW_REF"]=R+"/.github/workflows/actions_delete.yml@"+env["GITHUB_REF"]
    trace=Mock()
    api=Mock(side_effect=[comment,approved_pr])
    trace.attach_mock(api,"api")
    context=ActionsContext(args,env=env,api=api)
    read=Mock(return_value=event)
    trace.attach_mock(read,"read")
    with patch.object(context,"read_event",read):
        record("actions_context:"+name,lambda:context.validate().targets,trace)
from tests.suites.registry_contract import RegistryContract
for name,names,registered in (("exact",("registry",),{"registry":RegistryContract}),
                              ("wrong_key",("other",),{"other":RegistryContract}),
                              ("wrong_class",("registry",),{"registry":BadSuite})):
    # A count changes when new self-tests are added; compare only whether the exact class is loaded.
    def check_exemption():
        loaded=build_suite(names=names,registered=registered)
        return bool(loaded.countTestCases()) and all(type(test) is RegistryContract for test in loaded)
    record("test_exemption:"+name,check_exemption,Mock())
for name in ("compact","split","expected_exception","unexpected_exception","check_failure","suppressed","scenario","scenario_failure","matrix"):
    trace=Mock()
    suite=TestSuite()
    @contextlib.contextmanager
    def scope(ctx):
        trace.enter()
        ctx.value=1
        try:
            yield
        except ValueError:
            if name!="suppressed":
                raise
        finally:
            trace.exit()
    def action(ctx):
        trace.act(ctx.value)
        if name in ("expected_exception","unexpected_exception","suppressed"):
            raise ValueError("action failure")
        return 7
    def check(ctx,result=None):
        trace.check(ctx.value, str(result) if isinstance(result,Exception) else result)
        if name=="check_failure": raise ValueError("check failure")
    def first(ctx):
        trace.first(ctx.value)
        ctx.value=2
        if name=="scenario_failure": raise ValueError("step failure")
    def second(ctx):
        trace.second(ctx.value)
    def matrix(ctx,value):
        trace.row(value,hasattr(ctx,"seen"))
        ctx.seen=True
    def run_test():
        try:
            if name=="compact": suite.run_contract(check=check,arrange=scope)
            elif name in ("scenario","scenario_failure"): suite.run_scenario((("first",first),("second",second)),check,arrange=scope)
            elif name=="matrix": suite.run_cases((("a",1),("b",2)),matrix)
            else: suite.run_contract(action,check,arrange=scope,raises=ValueError if name=="expected_exception" else None)
            return "ok"
        except Exception as error:
            return [type(error).__name__,str(error),getattr(error,"__notes__",[])]
    record("test_scope:"+name,run_test,trace)
for runner in ("contract","scenario"):
    for failure in ("entry","body","exit","suppression"):
        trace=Mock()
        original=StopIteration("original")
        cleanup=RuntimeError("cleanup")
        class Scope:
            def __enter__(self):
                trace.enter()
                if failure=="entry":
                    raise original
            def __exit__(self,typ,error,tb):
                trace.exit(type(error).__name__ if error is not None else None,error is original)
                if failure=="exit":
                    raise cleanup
                return failure=="suppression"
        def arrange(ctx):
            trace.arrange()
            return Scope()
        def act(ctx):
            trace.act()
            if failure in ("body","suppression"):
                raise original
            return 7
        def check(ctx,result=None):
            trace.check(result)
        def run_scoped():
            try:
                if runner=="contract":
                    TestSuite().run_contract(act,check,arrange=arrange)
                else:
                    TestSuite().run_scenario((("step",act),),check,arrange=arrange)
                return "ok"
            except Exception as e:
                return [type(e).__name__,str(e),e is original,e is cleanup,getattr(e,"__notes__",[])]
        record("scope_identity:"+runner+"_"+failure,run_scoped,trace)
from app.wiring import resolve_execution
from app.commands import execute as execution_command
from pathlib import Path
import sys
for label, expression, parameters in (
    ("valid", "pr_merge.py - branch_delete.py", "{}"),
    ("bad_parameters", "unknown.py", "[]"),
    ("unknown_duplicate", "unknown.py - unknown.py", "{}"),
    ("duplicate", "pr_merge.py - pr_merge.py", "{}"),
    ("reverse", "branch_delete.py - pr_merge.py", "{}"),
    ("empty", "", "{}"),
    ("malformed_json", "pr_merge.py", "{")):
    record("execution_resolution:"+label,lambda:resolve_execution(expression,parameters),Mock())
for label, chain, codes, stage in (
    ("empty", (), (), None),
    ("unknown", ("unknown.py",), (), None),
    ("late_unknown", ("pr_merge.py","unknown.py"), (), None),
    ("success", ("pr_merge.py","branch_delete.py"), (0,0), None),
    ("positive_failure", ("pr_merge.py","branch_delete.py"), (7,), None),
    ("negative_failure", ("pr_merge.py","branch_delete.py"), (-9,), None),
    ("first_stage", ("pr_merge.py","branch_delete.py"), (0,), 1),
    ("second_stage", ("pr_merge.py","branch_delete.py"), (0,), 2),
    ("invalid_stage", ("pr_merge.py","branch_delete.py"), (), 3),
    ("invalid_cardinality", ("pr_merge.py",), (), 1)):
    trace=Mock()
    statuses=iter(codes)
    def run_process(argv, *, cwd, check):
        trace.run(argv[1:],cwd == Path.cwd(),check)
        return SimpleNamespace(returncode=next(statuses))
    record("execution_sequence:"+label,lambda:execution_command.run_execution(chain,run=run_process) if stage is None else execution_command.run_stage(chain,stage,run=run_process),trace)
for label, request in (
    ("single", {"execution":"delete actions","run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}),
    ("batch_order", {"execution":"delete actions","runs":[{"run_id":14,"expected_head_sha":SHA,"expected_run_attempt":1},{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}]}),
    ("missing", {"execution":"delete actions","run_id":12,"expected_head_sha":SHA}),
    ("extra", {"execution":"delete actions","run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1,"extra":True}),
    ("bool", {"execution":"delete actions","run_id":True,"expected_head_sha":SHA,"expected_run_attempt":1}),
    ("batch_extra", {"execution":"delete actions","runs":[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1,"extra":True}]})):
    record("actions_wire:"+label,lambda:actions.actions_request(request),Mock())
validate_method = library("testing").validate_method
from textwrap import dedent
def method(body):
    return "def test_sample(self):\n" + "\n".join("    "+line for line in body.splitlines())+"\n"
compact="def check(ctx):\n    pass\nself.run_contract(check=check)"
split="def act(ctx):\n    pass\ndef check(ctx, result):\n    pass\nself.run_contract(act, check, raises=ValueError)"
cases="cases=(('one',1),)\ndef check(ctx, value):\n    pass\nself.run_cases(cases, check)"
scenario="def first(ctx):\n    pass\ndef check(ctx):\n    pass\nsteps=(('first', first),)\nself.run_scenario(steps, check)"
for label, source in (
    ("compact",method(compact)), ("split",method(split)), ("cases",method(cases)), ("scenario",method(scenario)),
    ("docstring",method('"""test description"""\n'+compact)),
    ("bad_envelope","def test_sample(self, extra):\n    pass"),
    ("not_function","x = 1"), ("no_runner",method("pass")),
    ("multiple_runner",method(compact+"\nself.run_contract(check=check)")),
    ("self_ctx",method(compact.replace("    pass","    self.ctx"))),
    ("bad_callback",method(compact.replace("check(ctx)","check(other)"))),
    ("annotated_callback",method(compact.replace("check(ctx)","check(ctx: object)"))),
    ("duplicate_callback",method("def check(ctx):\n    pass\n"+compact)),
    ("duplicate_data",method("a=1\na=2\n"+compact)),
    ("arbitrary_declaration",method("x=print('x')\n"+compact)),
    ("executable_statement",method("print('x')\n"+compact)),
    ("unknown_keyword",method(compact.replace("check=check","check=check, extra=True"))),
    ("unpacked_keywords",method(compact.replace("check=check","**kwargs"))),
    ("compact_raises",method(compact.replace("check=check","check=check, raises=ValueError"))),
    ("split_invalid_raises",method(split.replace("raises=ValueError","raises=make_error()"))),
    ("bad_cases",method(cases.replace("run_cases(cases, check)","run_cases(cases, check, arrange=check)"))),
    ("bad_scenario_table",method(scenario.replace("steps=(('first', first),)","steps=()"))),
    ("bad_scenario_row",method(scenario.replace("('first', first)","('first', 1)"))),
    ("missing_step",method(scenario.replace("('first', first)","('first', second)"))),
    ("wrong_arrange",method(compact.replace("check=check","check=check, arrange=check"))),
    ("unused_callback",method("def unused(ctx):\n    pass\n"+compact)),
    ("precedence",method("x=print('x')\n"+compact.replace("check=check","check=check, raises=ValueError")))):
    record("test_grammar:"+label,lambda:validate_method(source),Mock())
# Cross product of malformed and valid forms. Keep original exception type/message.
from itertools import product
body_prefix = ("cases=(('one', 1),)\nsteps=(('first', first),)\n"
               "def first(ctx):\n    pass\ndef act(ctx):\n    pass\n"
               "def check(ctx):\n    pass\ndef arrange(ctx):\n    pass\n")
positional = ("", "cases, check", "act, check", "steps, check", "wrong, check",
              "check", "act, wrong", "*args", "cases, check, act")
kw = ("", "check=check", "check=wrong", "arrange=arrange", "arrange=wrong",
      "raises=ValueError", "raises=bad()", "raises=ValueError, arrange=wrong",
      "raises=bad(), arrange=wrong", "other=True", "check=check, raises=bad()",
      "check=check, arrange=wrong", "check=check, check=check", "**other")
for runner, (pi, pos), (ki, keyword) in product(("run_cases","run_contract","run_scenario"),
                                               enumerate(positional),enumerate(kw)):
    args = ", ".join(x for x in (pos,keyword) if x)
    text = method(body_prefix+"self."+runner+"("+args+")")
    record("grammar_matrix:"+runner+":"+str(pi)+":"+str(ki),lambda:validate_method(text),Mock())
# Independently exercise accepted callback ownership and scenario data errors.
for label, prefix, invoke in (
    ("compact_arrange", "def arrange(ctx):\n    pass\n"+compact.split("self.run_contract")[0], "self.run_contract(check=check, arrange=arrange)"),
    ("split_arrange", "def arrange(ctx):\n    pass\n"+split.split("self.run_contract")[0], "self.run_contract(act, check, raises=ValueError, arrange=arrange)"),
    ("scenario_arrange", "def arrange(ctx):\n    pass\n"+scenario.split("self.run_scenario")[0], "self.run_scenario(steps, check, arrange=arrange)"),
    ("scenario_bad_table_first", scenario.replace("steps=(('first', first),)","steps=()").split("self.run_scenario")[0], "self.run_scenario(steps, check, arrange=wrong)"),
    ("scenario_bad_row_first", scenario.replace("('first', first)","('first', 1)").split("self.run_scenario")[0], "self.run_scenario(steps, check, arrange=wrong)"),
    ("compact_raises_first", compact.split("self.run_contract")[0], "self.run_contract(check=check, raises=bad(), arrange=wrong)"),
    ("split_raises_first", split.split("self.run_contract")[0], "self.run_contract(act, check, raises=bad(), arrange=wrong)"),
    ("no_cases_decl", compact.split("self.run_contract")[0], "self.run_cases(cases, check)"),
    ("no_steps_decl", compact.split("self.run_contract")[0], "self.run_scenario(steps, check)")):
    record("grammar_precedence:"+label,lambda:validate_method(method(prefix+invoke)),Mock())
# D2: policy shape, range/type/list validation and precedence; patch only registry data.
from itertools import product
def policy_value(maximum=30, keep=1, paths=None, pins=None):
    return {"max_batch":maximum,"keep_successful":keep,
            "protected_workflows":[".github/workflows/a.yml"] if paths is None else paths,
            "pinned_run_ids":[] if pins is None else pins}
dimensions = (
    (1,50,0,51,True,1.0),
    (1,20,0,21,False),
    ([".github/workflows/a.yml"],[".github/workflows/a-b_2.yaml"],[],["../a.yml"],
     [".github/workflows/a.yml",".github/workflows/a.yml"],[[]]),
    ([],[1],[0],[True],[1,1],[[]]),
)
def inspect_policy(value):
    result=actions.actions_policy()
    return {"policy":result,"same_object":result is value}
for index, (maximum,keep,paths,pins) in enumerate(product(*dimensions)):
    value=policy_value(maximum,keep,paths,pins)
    trace=Mock()
    load=Mock(return_value=value)
    trace.attach_mock(load,"load")
    with patch.object(actions,"load_registry",load):
        record("policy_matrix:"+str(index),lambda:inspect_policy(value),trace)
for label,value in (
    ("not_dict",[]),("empty",{}),("missing",{"max_batch":False}),
    ("extra",dict(policy_value(),unexpected=True)),
    ("paths_tuple",policy_value(paths=(".github/workflows/a.yml",))),
    ("pins_tuple",policy_value(pins=(1,))),
    ("paths_none",dict(policy_value(),protected_workflows=None)),
    ("pins_none",dict(policy_value(),pinned_run_ids=None))):
    trace=Mock()
    load=Mock(return_value=value)
    trace.attach_mock(load,"load")
    with patch.object(actions,"load_registry",load):
        record("policy_shape:"+label,lambda:inspect_policy(value),trace)
for label, targets in (
    ("empty",[]),("nonlist",()),("valid",[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}]),
    ("shape",[{"run_id":False}]),
    ("integer_first",[{"run_id":False,"expected_head_sha":"bad","expected_run_attempt":0}]),
    ("attempt_first",[{"run_id":12,"expected_head_sha":"bad","expected_run_attempt":True}]),
    ("sha_first",[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1},{"run_id":12,"expected_head_sha":"bad","expected_run_attempt":1}]),
    ("duplicate_first",[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1},{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1},{}])):
    trace=Mock()
    value=policy_value()
    load=Mock(return_value=value)
    trace.attach_mock(load,"load")
    with patch.object(actions,"load_registry",load):
        record("target_validation:"+label,lambda:actions.validate_actions_targets(targets),trace)
for label, value, targets, current in (
    ("policy_shape",{"max_batch":False},[],13),
    ("policy_first",policy_value(maximum=False),[],13),
    ("target_first",policy_value(),[{}],False),
    ("integer_first",policy_value(),[{"run_id":True,"expected_head_sha":"bad","expected_run_attempt":1}],13),
    ("current_invalid",policy_value(),[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}],False),
    ("current_target",policy_value(),[{"run_id":12,"expected_head_sha":SHA,"expected_run_attempt":1}],12)):
    trace=Mock()
    load=Mock(return_value=value)
    api=Mock()
    remove=Mock()
    report=Mock()
    for name, mock in (("load",load),("api",api),("remove",remove),("report",report)):
        trace.attach_mock(mock,name)
    with patch.object(actions,"load_registry",load):
        record("policy_no_remote:"+label,lambda:actions.delete_actions_batch(api,remove,R,REF,targets,current,report=report),trace)
print(json.dumps(RESULTS,sort_keys=True))

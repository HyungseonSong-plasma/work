# FileRank: C
"""Versioned post-Q1/Q2 expected outcomes, with all remote operations mocked."""

import json
import os
from copy import deepcopy
from unittest.mock import Mock, patch
from types import SimpleNamespace
from github import actions, trigger
from libs.workflow import PRContext
from app.wiring import resolve_execution
from app.commands import execute
from app.commands.trigger import route_registry
from tests.fixtures import ActionsTestContext, REPO, REF, SHA

def capture(label, fn, expected):
    try:
        result = fn()
    except Exception as error:
        result = {"error":type(error).__name__, "message":str(error)}
    print(label, json.dumps(result,sort_keys=True), flush=True)
    assert result == expected, (label,result,expected)

def retention(label, *, keep=1, target_order=50, orders=(40,), total=None,
              target_present=False, target_conclusion="success", expected_remove=False,
              second_orders=None, second_total=None, mismatch=False):
    ctx=ActionsTestContext()
    path=".github/workflows/trigger.yml"
    target=dict(ctx.run_data,path=path,workflow_id=7,conclusion=target_conclusion,
                created_at=f"2026-01-01T00:{target_order:02d}:00Z")
    def listing(order_values, count):
        runs=[dict(target,id=100+i,conclusion="success",created_at=f"2026-01-01T00:{v:02d}:00Z")
              for i,v in enumerate(order_values)]
        if target_present:
            row=dict(target)
            if mismatch:
                row["created_at"]="2026-01-01T00:00:00Z"
            runs.append(row)
        runs.sort(key=lambda item:(item["created_at"],item["id"]),reverse=True)
        return {"total_count":len(runs) if count is None else count,"workflow_runs":runs}
    first=listing(orders,total)
    second=listing(orders if second_orders is None else second_orders,
                   total if second_total is None else second_total)
    ctx.api.side_effect=[ctx.repo,target,first,deepcopy(target),second]
    policy={"max_batch":30,"keep_successful":keep,"protected_workflows":[path],"pinned_run_ids":[]}
    result="accepted"
    with patch.object(actions,"actions_policy",return_value=policy):
        try:
            actions.delete_actions_batch(ctx.api,ctx.remove,REPO,REF,[ctx.target()],13,report=Mock())
        except ValueError as error:
            result=str(error)
    print(label,json.dumps({"outcome":result,"mock_delete":ctx.remove.call_count,"mock_get":ctx.api.call_count},sort_keys=True),flush=True)
    assert ctx.remove.call_count==int(expected_remove),label
    if not expected_remove:
        assert result != "accepted",label

retention("Q1_complete_missing_newest")
retention("Q1_complete_missing_older",target_order=10,orders=(40,))
retention("Q1_truncated_missing_newest",orders=(40,),total=101)
retention("Q1_truncated_missing_older",target_order=10,orders=(40,),total=101)
retention("Q1_keep2_missing_inside_cutoff",keep=2,target_order=35,orders=(40,30),total=101)
retention("Q1_keep2_missing_older",keep=2,target_order=10,orders=(40,30),total=101)
retention("Q1_empty_success",orders=())
retention("Q1_present_newest",target_present=True)
retention("Q1_present_older",target_present=True,target_order=10,expected_remove=True)
retention("Q1_present_order_mismatch",target_present=True,mismatch=True)
retention("Q1_tie_missing",target_order=40,orders=(40,),total=101)
retention("Q1_failure_not_in_success",target_conclusion="failure",expected_remove=True)
retention("Q1_fresh_listing_changes_to_inconsistent",target_order=35,orders=(40,30),total=101,second_orders=(20,),second_total=1)
retention("Q1_too_few_retained",keep=2,orders=(40,),total=101)
retention("Q1_full_page_missing_newest",orders=(40,)*100,total=101)
retention("Q1_full_page_missing_older",target_order=10,orders=(40,)*100,total=101,expected_remove=True)
retention("Q1_full_page_keep2_missing_inside_cutoff",keep=2,target_order=35,orders=(40,)+(30,)*99,total=101)
retention("Q1_full_page_tie_older_id",target_order=40,orders=(40,)*100,total=101,expected_remove=True)

def pr_worker(label,actor,request_id="",attempt="1",serial=False,event_repository=REPO,expected=True):
    ctx=ActionsTestContext()
    chain="pr_merge.py - branch_delete.py" if serial else "pr_merge.py"
    event={"repository":{"full_name":event_repository,"owner":{"id":1},"default_branch":"main"},
           "sender":{"id":int(actor)},"inputs":{"request_id":request_id,"execution":chain}}
    import tempfile, os
    with tempfile.TemporaryDirectory() as temp:
        from pathlib import Path
        file=Path(temp)/"event.json";file.write_text(json.dumps(event))
        env=ctx.environment(GITHUB_ACTOR_ID=actor,GITHUB_RUN_ATTEMPT=attempt,
              GITHUB_EVENT_PATH=str(file),GITHUB_WORKFLOW_REF=f"{REPO}/.github/workflows/"+("serial_run.yml" if serial else "single_run.yml")+"@"+REF,
              EXECUTION=chain)
        process=Mock(return_value=SimpleNamespace(returncode=0))
        with patch.dict(os.environ,env,clear=True), patch.object(execute,"run_execution",side_effect=lambda names, **kwargs: original(names,run=process)):
            try:
                execute.ExecuteCommand.execute(SimpleNamespace(single=not serial,serial_stage=1 if serial else None))
                PRContext("pr_merge.py",env=env,resolve=resolve_execution).validate()
                accepted=True
            except ValueError:
                accepted=False
        print(label,json.dumps({"accepted":accepted,"mock_subprocess":process.call_count,"actor_fixture":actor,"source":request_id},sort_keys=True),flush=True)
        assert accepted==expected and process.call_count==int(expected),label
original=execute.run_execution
pr_worker("Q2_owner_manual","1")
pr_worker("Q2_nonowner_manual","2")
pr_worker("Q2_nonowner_source_label","2","comment-999")
pr_worker("Q2_bot_without_source","41898282")
pr_worker("Q2_bot_with_source_label","41898282","comment-999")
pr_worker("Q2_nonowner_serial","2",serial=True)
pr_worker("Q2_event_repo_mismatch","1",event_repository="other/repo")
pr_worker("Q2_rerun","1",attempt="2",expected=False)
ctx=ActionsTestContext()
def actions_approval(actor):
    event=ctx.approval_event()
    event["sender"]["id"]=int(actor)
    try:
        ctx.validate_context(event,REPO,REF,actor,ctx.workflow_ref,api=Mock())
        return "accepted"
    except ValueError as error:
        return str(error)
capture("Q2_actions_owner_manual",lambda:actions_approval("1"),"accepted")
capture("Q2_actions_nonowner_manual",lambda:actions_approval("2"),"Manual deletion requires the owner.")
event=ctx.event("pr_merge.py")
event["sender"]["id"]=2
event["comment"]["user"]["id"]=2
capture("Q2_trigger_nonowner",lambda:trigger.route(event,REPO,REF,routes=route_registry,resolve=resolve_execution),
        {"error":"ValueError","message":"Unauthorized execution comment."})
print("Q1 18 and Q2 11 expected snapshot outcomes passed",flush=True)

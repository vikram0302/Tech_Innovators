from __future__ import annotations

try:
    from google.adk.agents import Agent

    from backend.agent import tools

    root_agent = Agent(
        name="claims_audit_agent",
        model="gemini-2.0-flash",
        description="Claims Audit Agent — audits uploaded claims against uploaded regulations.",
        instruction=(
            "You are the Claims Audit Agent. Regulations come ONLY from the Regulations tab uploads — "
            "never from chat attachments. Claims data comes from dataset uploads. "
            "Use get_active_regulations, list_dataset_claims, create_batch_audit_plan, "
            "run_batch_audit, get_combined_report. Never override deterministic check results."
        ),
        tools=[
            tools.get_active_regulations_tool,
            tools.list_dataset_claims_tool,
            tools.create_batch_audit_plan_tool,
            tools.run_batch_audit_tool,
            tools.get_batch_status_tool,
            tools.get_combined_report_tool,
            tools.load_claim_tool,
            tools.get_rule_catalog_tool,
        ],
    )
except ImportError:
    root_agent = None

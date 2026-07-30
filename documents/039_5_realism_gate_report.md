# 039.5 Realism Gate Report

Final decision: `PASS`

## Scope

This report closes Phase 039.5 for the synthetic multi-city realism baseline.
The dataset is fully synthetic and does not represent real operator inventory,
customers, tariffs, incidents, alarms, policies, or live network data.

## Exact Data Volumes

- Dataset: `multi-city-realism-v1`
- Snapshot: `Multi-city Realism Snapshot v1`
- Snapshot state: passive, `validated`, validation status `exact`
- Active snapshot remains: `Maltepe MVP Snapshot`
- Customers: 14,400
- Subscriptions: 16,200
- SubscriptionConnection: 16,235
  - primary: 16,027
  - backup: 208
- LineConnection: 16,235
- NetworkPort: 13,664
- FailureDomain: 2,997

## Topology Summary

- Cities: 4
- Districts: 12
- Neighborhoods: 59
- NetworkDevice: 235
  - BNG: 8
  - metro aggregation: 16
  - OLT: 32
  - DSLAM: 95
  - standard access node: 51
  - corporate fiber aggregation access node: 33
- NetworkLink: 245
- Primary topology: `BNG -> metro aggregation -> access device -> service port`
- Path diversity:
  - fully_diverse: 112
  - partially_diverse: 60
  - shared_risk: 24
  - unknown: 12

## Alarm And Event Scope

- AlarmType: 30
- Alarm: 2,100
  - cleared: 1,680
  - open: 210
  - suppressed: 210
- Incident: 210
- Outage: 78
- MaintenanceWindow: 30
- OperationalEvent: 900
- QualityMeasurement: 12,000
- Degradation incidents do not create Outage rows.
- Protection-loss incidents do not create Outage rows.
- Noise alarms do not create incidents by themselves.

## Commercial And SLA Scope

- ServicePackage: 27
- SLAProfile: 5
- Campaign: 10
- ServicePackagePriceVersion: 72
- PaymentRecord: 59,600
- CampaignEnrollment: 4,050
- CompensationHistory: 1,100

## Rule Summary

- RuleSet: `SYN-COMP-2026` v1
- Rule: 25
- Active RuleVersion: 25
- DecisionEvidence: 227 finalized records with 64-character evidence hashes.
- `REFUND-001` remains isolated to the Maltepe MVP regression dataset.

## Ground Truth

- Multi-city ground-truth cases: 30
- Result: 30 passed, 0 failed
- Ground truth validates network operation, compensation, path diversity,
  maintenance, duplicate prevention, manual-review, and noise cases.

## Service And Performance Smoke

Representative native PostgreSQL smoke results:

- BNG topology subgraph: 0.0384 s
- Alarm correlation sample: 0.0354 s
- Root cause for `OUT-MCR-0001`: 0.0436 s
- Customer impact for `OUT-MCR-0001`: 1.9598 s
- Path diversity sample: 0.0441 s
- Rule evaluation: 0.0524 s
- Compensation amount calculation: 0.0422 s
- DecisionEvidence lookup: 0.0047 s

Additional checks:

- Fiber-route RCA/impact smoke completed.
- Power-zone RCA/impact smoke completed.
- Failed failover impact smoke completed.
- Degradation incident count: 60, outage count: 0
- Protection-loss incident count: 22, outage count: 0

## Maltepe Regression

- Active snapshot: `Maltepe MVP Snapshot`
- Outage: `OUT-MAL-BNG-001`
- Affected subscriptions: 150
- Affected customers: 140
- Rule: `REFUND-001` v2
- Expected refund total: 5,173.50 TRY

## Known Limits

- This is synthetic realism data, not real operator data.
- Comprehensive SRLG modeling is intentionally not included.
- There is no production network integration.
- SimulationRun runtime, virtual clock, replay, and live event stream are planned
  for Tasks 075-081.
- RAG will be decided separately and will only retrieve policy/procedure sources.
- LLM will orchestrate tools and explain deterministic outputs; it will not
  calculate eligibility or amounts.

## Final Decision

`PASS`

Phase 039.5 multi-city synthetic realism v1 is closed. Geography, topology,
customer, package, SLA, alarm, event, and business-rule decisions are frozen as
the baseline for subsequent tasks. Future changes require a separate change note
and regression validation.

# Unverified Threat Intel Queue

**Document ID:** UNVERIFIED_THREAT_INTEL_QUEUE  
**Version:** 1.0  
**Date:** 2026-07-03  
**Status:** STAGING — entries below are UNVERIFIED and do not constitute confirmed doctrine

---

## Purpose

This queue stages threat intelligence that has been received but not yet verified against an authoritative source. No entry here may be cited as confirmed doctrine, referenced in Sentinel rules, or included in OverWatch thresholds until it has passed the promotion criteria below.

---

## Promotion Criteria

An entry may be promoted to confirmed doctrine when **all** of the following are met:

1. A verified authoritative source is provided: NVD entry, vendor security advisory, or peer-reviewed security research paper.
2. The source URL or citation is confirmed reachable and authentic.
3. The entry is reviewed against existing SENTINEL_PATTERNS and TAX2 vectors to determine whether a new rule or an update to an existing rule is required.
4. The doctrine change is committed under the standard GovSec version bump process.

Until promotion, entries remain in this file with `status: UNVERIFIED`.

---

## Queue Entries

### QUEUE-001 — DuneSlide

```yaml
id: QUEUE-001
name: DuneSlide
description: >
  Alleged technique for sliding adversarial payloads past classification 
  systems using Unicode normalization inconsistencies.
status: UNVERIFIED
source_required: YES
source_provided: NO
date_received: 2026-07-03
notes: >
  No authoritative source, CVE, or research paper has been provided.
  Cannot enter doctrine. Do not reference in Sentinel rules or OverWatch thresholds.
```

### QUEUE-002 — CVE-2026-50548

```yaml
id: QUEUE-002
name: CVE-2026-50548
description: >
  Alleged critical vulnerability in an unspecified LLM routing component.
status: UNVERIFIED
source_required: YES
source_provided: NO
date_received: 2026-07-03
notes: >
  No NVD entry, vendor advisory, or CVSS score has been provided.
  This CVE ID has not been verified as assigned or published.
  Cannot enter doctrine until NVD or vendor confirmation is provided.
```

### QUEUE-003 — CVE-2026-50549

```yaml
id: QUEUE-003
name: CVE-2026-50549
description: >
  Alleged critical vulnerability in an unspecified LLM governance layer.
status: UNVERIFIED
source_required: YES
source_provided: NO
date_received: 2026-07-03
notes: >
  No NVD entry, vendor advisory, or CVSS score has been provided.
  This CVE ID has not been verified as assigned or published.
  Cannot enter doctrine until NVD or vendor confirmation is provided.
```

---

## How to Submit an Entry for Promotion

Open a governance review with:

- The entry ID from this queue
- The authoritative source (URL + date accessed, or full citation)
- The proposed rule change (new SENT rule, updated OW threshold, or TAX2 vector)
- Confirmation that the proposed change does not weaken any existing governance layer

Entries that cannot satisfy all promotion criteria remain in this queue indefinitely.

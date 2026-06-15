## House Padi Leasing Flow Documentation

This document describes the complete renter and landlord workflows for the leasing process.

### Architecture Overview

**New Agents:**
- `renter`: Guides renters through property search, tour booking, application submission, and lease signing
- `landlord`: Enables landlords to manage tour requests, review applications, and sign leases

**New Tools (24 total):**

#### Application Management (6 tools)
- `apply_for_property`: Renter submits application for a property
- `view_applications`: Landlord views all applications for their property
- `view_application_details`: Get details of a specific application
- `approve_application`: Landlord approves a renter's application
- `deny_application`: Landlord denies an application with optional reason
- `get_renter_applications`: Renter views their own applications

#### Lease Management (5 tools)
- `create_lease`: Create a lease contract after application approval
- `sign_lease`: Renter or landlord signs the lease
- `get_lease_details`: View lease contract details
- `get_active_leases`: View all active leases (as renter or landlord)
- `terminate_lease`: Terminate an active lease

#### Tour Management (Landlord-side, 5 new tools)
- `view_tour_requests`: Landlord views all tour requests for a property
- `approve_tour_request`: Landlord approves a tour request
- `deny_tour_request`: Landlord denies a tour request
- `reschedule_tour`: Landlord reschedules a tour to a new date
- `get_renter_tour_requests`: Renter views their own tour requests

---

## RENTER WORKFLOW

### Phase 1: Property Discovery & Interest
**Flow:** `renter` agent → `search_semantic_listings` → Filter by preferences

**User Intent:** "I'm looking for a 2-bedroom apartment in Lagos with a budget of 500,000 naira"

**Expected Output:**
```
Here are some 2-bedroom apartments in Lagos within your budget:
1. Beautiful apartment in Ikoyi - ₦450,000/month
2. Modern flat in Victoria Island - ₦480,000/month
3. Cozy apartment in Yaba - ₦420,000/month

Would you like to see more details about any of these, or book a tour?
```

### Phase 2: Tour Booking
**Flow:** `renter` agent → `schedule_tour` → Tour request sent to landlord

**User Intent:** "I'd like to tour the apartment in Ikoyi tomorrow at 2 PM"

**Expected Output:**
```
Your tour has been scheduled for tomorrow at 2:00 PM at the Ikoyi apartment.
The landlord will receive your request and confirm within 24 hours.
In the meantime, feel free to search for other properties.
```

**Landlord Receives:**
- Tour request notification with renter details and preferred time
- Options to approve, deny, or reschedule

### Phase 3: Application Submission (After Positive Tour)
**Flow:** `renter` agent → `apply_for_property` → Application data

**User Intent:** "I loved the apartment! I'd like to apply for it."

**System Prompt to Renter:**
```
To complete your application, I'll need:
1. Your employment status (employed/self-employed/student)
2. Monthly income
3. References (landlord or employer contact)
4. Move-in date preference
```

**Expected Output After Data Collection:**
```
Your application has been submitted to the landlord.
The landlord will review it and respond within 2-3 business days.
Keep an eye on your notifications for updates.
```

### Phase 4: Lease Signing (After Application Approval)
**Flow:** `renter` agent → `sign_lease` → Lease agreement

**Landlord Action:** Approves application → `create_lease` → Lease sent to renter

**Renter Receives:**
```
Great news! Your application has been approved!
A lease agreement has been sent to you with the following terms:
- Monthly rent: ₦450,000
- Lease duration: 12 months
- Move-in date: June 15, 2026
- Deposit: ₦450,000

Please review and sign the lease to finalize the deal.
```

**User Intent:** "I'll sign the lease"

**Expected Output:**
```
Lease signed by you. The landlord will review and sign to complete the agreement.
Once both parties sign, your lease will be active and you'll receive all lease documents.
```

---

## LANDLORD WORKFLOW

### Phase 1: Receive & Manage Tour Requests
**Flow:** Renter submits tour request → `landlord` agent → `view_tour_requests`

**Landlord Intent:** "Show me all tour requests for my Ikoyi property"

**Expected Output:**
```
You have 3 tour requests for your Ikoyi property:

1. John Doe - Requested for June 15 at 2:00 PM
   Contact: john@example.com | +234 812 345 6789
   [Approve] [Deny] [Reschedule]

2. Jane Smith - Requested for June 16 at 10:00 AM
   Contact: jane@example.com | +234 902 345 6789
   [Approve] [Deny] [Reschedule]

3. Michael Johnson - Requested for June 17 at 4:00 PM
   Contact: michael@example.com | +234 913 345 6789
   [Approve] [Deny] [Reschedule]
```

**Actions:**
- **Approve:** `approve_tour_request` → Renter receives confirmation
- **Deny:** `deny_tour_request` → Renter receives denial reason
- **Reschedule:** `reschedule_tour` → New time sent to renter for confirmation

### Phase 2: Review & Manage Applications
**Flow:** Renter submits application → `landlord` agent → `view_applications`

**Landlord Intent:** "Show me all applications for my Ikoyi property"

**Expected Output:**
```
You have 2 applications for your Ikoyi property:

1. John Doe - Applied on June 15
   Employment: Employed at Tech Company
   Monthly Income: ₦800,000
   References: previous_landlord@email.com
   Status: Pending
   [View Details] [Approve] [Deny]

2. Jane Smith - Applied on June 16
   Employment: Self-employed (Consultant)
   Monthly Income: ₦1,200,000
   References: jane_employer@email.com
   Status: Pending
   [View Details] [Approve] [Deny]
```

**Landlord Intent:** "Approve Jane Smith's application"

**Expected Output:**
```
Application approved! A lease agreement will be prepared and sent to Jane Smith immediately.
She'll receive the lease terms and will need to sign within 3 days.
```

**Landlord Intent:** "Deny John Doe's application due to insufficient income"

**Expected Output:**
```
Application denied. John Doe will be notified with the reason:
"Unfortunately, your monthly income does not meet our minimum requirement."

You can send him alternative property recommendations.
```

### Phase 3: Create & Sign Lease
**Flow:** Application approved → `create_lease` → Both parties sign

**System Action (Automatic on Approval):**
- Lease document generated with:
  - Property details
  - Monthly rent amount
  - Lease duration
  - Move-in date
  - Security deposit terms
  - Payment schedule

**Landlord Intent:** "I want to view the lease for John's application to make sure the terms are correct"

**Expected Output:**
```
Lease #UUID details:
- Property: Ikoyi apartment (3 bedrooms, 2 bathrooms)
- Renter: John Doe
- Monthly Rent: ₦450,000
- Lease Term: 12 months (June 15, 2026 - June 14, 2027)
- Security Deposit: ₦450,000
- Payment Due: 1st of each month

Lease Status: Unsigned (Awaiting signatures)
[Sign Lease] [Edit Terms] [Send Reminder]
```

**Landlord Signs:**
```
Lease signed by you!
The renter will be notified to review and sign the lease.
Once both parties sign, the lease becomes active.
```

### Phase 4: Monitor Active Leases
**Flow:** Both parties signed → Lease active

**Landlord Intent:** "Show me all my active leases"

**Expected Output:**
```
You have 3 active leases:

1. John Doe - Ikoyi apartment
   Rent: ₦450,000/month
   Duration: 12 months (June 15, 2026 - June 14, 2027)
   Monthly Payment: Due on 1st
   Days Remaining: 360
   Status: Active
   [View Details] [Send Reminder] [Terminate]

2. Jane Smith - Victoria Island apartment
   Rent: ₦580,000/month
   Duration: 12 months (June 1, 2026 - May 31, 2027)
   Monthly Payment: Due on 15th
   Days Remaining: 350
   Status: Active
   [View Details] [Send Reminder] [Terminate]

3. Michael Johnson - Yaba apartment
   Rent: ₦320,000/month
   Duration: 6 months (April 1, 2026 - September 30, 2026)
   Monthly Payment: Due on 10th
   Days Remaining: 112
   Status: Active (Ending Soon)
   [View Details] [Send Reminder] [Renew] [Terminate]
```

---

## Future Enhancements (DO NOT IMPLEMENT YET)

These features are designed with extensibility in mind but are NOT part of Phase 1:

1. **Calendar Integration Agent**
   - Sync tour dates with landlord's calendar
   - Automatic reminder notifications

2. **Notification Agent**
   - Send email confirmations for tour approvals
   - SMS/WhatsApp reminders for lease signings
   - Payment reminders (automated)

3. **Lease Tracking Agent**
   - Monitor lease expiration dates
   - Send renewal notifications 30/60/90 days before expiry
   - Track late payments

4. **Document Management**
   - Store signed lease PDFs
   - Generate lease contracts with dynamic fields
   - Archive completed leases

### Design Principles for Future Extensibility

1. **Agent Independence:** Each new agent should be self-contained with its own tool set
2. **Tool Composability:** New tools should leverage existing database tables
3. **Message Routing:** The orchestrator's router node will automatically direct to new agents
4. **Backward Compatibility:** Existing agents should not require changes

---

## Database Schema

### applications table
```sql
id, property_id, renter_id, status, application_data, 
approved_by, approved_at, denied_by, denial_reason, denied_at, 
created_at, updated_at
```

### leases table
```sql
id, property_id, renter_id, landlord_id, lease_terms, status, 
signed_by (JSON), signed_at, termination_reason, terminated_at,
created_at, updated_at
```

### tours table (updated)
```sql
... existing fields ...
visitor_id, denial_reason
```

---

## Human-Readable Response Guidelines

All agent responses must follow these rules:

✅ **DO:**
- Use natural language (no JSON, no code)
- Ask clarifying questions clearly
- Provide next-step guidance
- Use friendly, professional tone
- Format options clearly (1. Option A, 2. Option B)

❌ **DON'T:**
- Output raw JSON or database records
- Use technical jargon
- Show tool names or parameters
- Provide pseudo-code or API documentation
- Mix tools with conversational text

**Example of Correct Response:**
```
I found 3 properties that match your criteria. The most popular one is 
a beautiful 2-bedroom in Ikoyi for ₦450,000 per month. It has a modern 
kitchen and secured parking. Would you like to book a tour for it?
```

**Example of Incorrect Response:**
```
{
  "status": "SUCCESS",
  "properties": [
    {"id": "uuid123", "address": "Ikoyi", "price": 450000, ...}
  ]
}

Search completed. Call schedule_tour with property_id and tour_date.
```

---

## Testing Scenarios

### Scenario 1: Complete Renter Journey (Happy Path)
1. Renter searches for 2-bed apartment in Lagos, budget ₦500k
2. Renter books tour for apartment in Ikoyi
3. Landlord approves tour
4. Renter applies for apartment
5. Landlord approves application
6. Lease created and sent to both parties
7. Both renter and landlord sign lease
8. Lease becomes active

### Scenario 2: Landlord Denies Tour Request
1. Renter requests tour
2. Landlord denies with reason "Apartment already rented"
3. System suggests alternative properties to renter

### Scenario 3: Landlord Denies Application
1. Renter applies for property
2. Landlord reviews application and denies with reason
3. Renter receives notification with feedback
4. Renter can search for other properties

### Scenario 4: Lease Termination
1. Active lease exists between renter and landlord
2. Landlord initiates lease termination
3. System archives lease record
4. Both parties receive confirmation

---

## Implementation Checklist

✅ Created `mcp_application.py` with 6 tools
✅ Created `mcp_lease.py` with 5 tools
✅ Updated `mcp_tour.py` with 5 landlord-side tools
✅ Added validators for all new tools in `tool_validators.py`
✅ Created migration: `20260608_add_applications_and_leases.sql`
✅ Registered `renter` agent with authorized tools
✅ Registered `landlord` agent with authorized tools
✅ Updated `prompts.json` with new agent instructions
✅ Updated `mcp_oracle.py` to expose all new tools
✅ All type checking passes (no errors)

**Next Steps for Testing:**
1. Apply migration to Supabase database
2. Test renter workflow end-to-end
3. Test landlord workflow end-to-end
4. Verify human-readable responses (no JSON output)
5. Document any edge cases or improvements

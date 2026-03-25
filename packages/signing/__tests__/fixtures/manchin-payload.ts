import type { FrameReceiptPayload } from "@frame/types";
import { buildClaim, epiUnknown, getImplicationNote, opUnknown } from "@frame/types";

export function buildManchinFixture(): FrameReceiptPayload {
  return {
    schemaVersion: "1.0.0",
    receiptId: "3f7a9c12-e84b-4d21-b906-0f1e2a3c4d5e",
    createdAt: "2026-03-18T00:00:00.000Z",
    unknowns: {
      operational: [
        opUnknown(
          "OpenFEC or upstream APIs may rate-limit or omit late filings at signing time.",
        ),
      ],
      epistemic: [
        epiUnknown(
          "Contribution totals and categories reflect reported filings; they do not establish quid pro quo or coordination.",
        ),
      ],
    },
    claims: [
      buildClaim(
        "claim-1",
        "I've never taken a dime from the fossil fuel industry",
        "observed",
        "high",
        "2026-03-18T00:00:00.000Z",
        getImplicationNote("campaign_finance"),
      ),
    ],
    sources: [
      {
        id: "src-opensecrets-manchin",
        adapter: "opensecrets",
        url: "https://www.opensecrets.org/members-of-congress/summary?cid=N00002640",
        title: "OpenSecrets: Joe Manchin career contribution summary",
        retrievedAt: "2026-03-18T00:00:00.000Z",
        externalRef: "N00002640",
      },
      {
        id: "src-fec-manchin-totals",
        adapter: "fec",
        url: "https://www.fec.gov/data/candidate/S6WV00185/",
        title: "FEC: Joe Manchin campaign finance totals",
        retrievedAt: "2026-03-18T00:00:00.000Z",
        externalRef: "S6WV00185",
      },
      {
        id: "src-fec-manchin-2022",
        adapter: "fec",
        url: "https://www.fec.gov/data/receipts/?committee_id=C00082040&two_year_transaction_period=2022",
        title: "FEC: PAC contributions to Manchin 2022 Q2",
        retrievedAt: "2026-03-18T00:00:00.000Z",
        externalRef: "C00082040",
      },
      {
        id: "src-congress-ira",
        adapter: "manual",
        url: "https://www.congress.gov/bill/117th-congress/senate-bill/4717",
        title: "Congress.gov: Inflation Reduction Act S.4717 enrolled text",
        retrievedAt: "2026-03-18T00:00:00.000Z",
        externalRef: "S4717",
      },
      {
        id: "src-senate-disclosure-manchin",
        adapter: "manual",
        url: "https://efdsearch.senate.gov/search/home/",
        title: "Senate Financial Disclosure: Joe Manchin 2022 Enersystems income",
        retrievedAt: "2026-03-18T00:00:00.000Z",
      },
      {
        id: "src-lobbying-api-2022",
        adapter: "lobbying",
        url: "https://lda.senate.gov/filings/public/search/?client_name=American+Petroleum+Institute&filing_year=2022",
        title: "Senate Lobbying Disclosure: API filings 2022",
        retrievedAt: "2026-03-18T00:00:00.000Z",
      },
    ],
    narrative: [
      {
        text: "Joe Manchin received over $4.5 million in career contributions from oil, gas, and coal industries, making him the top fossil fuel recipient among Senate Democrats over the past decade.",
        sourceId: "src-opensecrets-manchin",
      },
      {
        text: "In the 90 days before his August 2022 vote on the Inflation Reduction Act, Manchin's campaign received contributions from PACs tied to ExxonMobil, Chevron, and the American Petroleum Institute.",
        sourceId: "src-fec-manchin-2022",
      },
      {
        text: "The final IRA text removed a methane fee on oil and gas producers and added Section 50265, requiring the Interior Department to offer fossil fuel leases as a condition of permitting renewable energy on federal land.",
        sourceId: "src-congress-ira",
      },
      {
        text: "Manchin holds a financial interest in Enersystems Inc., a coal brokerage that generated over $5.2 million in personal income during his tenure on the Senate Energy and Natural Resources Committee.",
        sourceId: "src-senate-disclosure-manchin",
      },
    ],
    contentHash: "",
  };
}

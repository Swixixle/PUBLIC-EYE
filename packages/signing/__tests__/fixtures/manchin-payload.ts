import type { FrameReceiptPayload } from "../../../types/index.js";

/**
 * Example receipt body for tests: public filings and neutral narrative only.
 * All narrative sentences include `sourceId` values present in `sources`.
 */
export function buildManchinFixture(): FrameReceiptPayload {
  return {
    schemaVersion: "1.0.0",
    receiptId: "550e8400-e29b-41d4-a716-446655440000",
    createdAt: "2024-01-15T12:00:00.000Z",
    claims: [
      {
        id: "claim-1",
        statement:
          "A senator received campaign contributions from donors in a reporting period covered by FEC filings.",
        assertedAt: "2024-01-10T00:00:00.000Z",
      },
    ],
    sources: [
      {
        id: "src-fec-c00783746",
        adapter: "fec",
        url: "https://www.fec.gov/data/committee/C00783746/",
        title: "FEC committee profile C00783746",
        retrievedAt: "2024-01-14T18:22:00.000Z",
        externalRef: "C00783746",
        metadata: { committeeId: "C00783746" },
      },
      {
        id: "src-os-n00032838",
        adapter: "opensecrets",
        url: "https://www.opensecrets.org/members-of-congress/summary?cid=N00032838",
        title: "OpenSecrets summary N00032838",
        retrievedAt: "2024-01-14T18:23:00.000Z",
        externalRef: "N00032838",
        metadata: { candidateId: "N00032838" },
      },
      {
        id: "src-lda-example",
        adapter: "lobbying",
        url: "https://lda.senate.gov/filings/public/filing/1234567/",
        title: "Lobbying disclosure filing 1234567",
        retrievedAt: "2024-01-14T18:24:00.000Z",
        externalRef: "1234567",
        metadata: { registrationId: "1234567" },
      },
    ],
    narrative: [
      {
        text: "The FEC lists committee C00783746 with filings available on the commission’s site.",
        sourceId: "src-fec-c00783746",
      },
      {
        text: "OpenSecrets publishes summary totals for candidate id N00032838.",
        sourceId: "src-os-n00032838",
      },
      {
        text: "The Senate LDA system hosts a disclosure page for registration 1234567.",
        sourceId: "src-lda-example",
      },
    ],
    contentHash: "",
  };
}

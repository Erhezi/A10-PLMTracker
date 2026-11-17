-- Order Timing: the schema and the views the module reads. Run on O2, database PLM. Safe to re-run.
-- No app deploy needed to change a view; the app needs the columns it reads (app/ordertiming/queries.py).
--
-- Medline's Order Detail feed ("Order Detail with Confirm and ASN Timing") is loaded by the A13
-- pipeline (reports/medline_ordertiming) into SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming:
-- one row per order line Medline received from us by EDI, keyed on (Report Date, Order #, Order Line).
-- Each load replaces its Report Date, so a day's lines are as of that day's latest file.
-- The web app never writes there; it reads only these views:
--
--   OrderTiming.vw_MedlineOrderLine      Medline's lines, as loaded, plus each step's date and time
--                                        as one value, the line's status (Line Status) and what
--                                        it's short shipped (Short Qty)
--   OrderTiming.vw_OrderTimingLastLoad   one row: how fresh the lines are, for the app's "Data as
--                                        of" (Medline's file) and "Last loaded"
--
-- Short Ships (2026-11-17) also reads Fill/Kill's FillKill.vw_MedlineFillKill (db/fillkill/10):
-- each short line's kill reason, and how often each item was killed.
--
-- Line Status and Short Qty are the rules the app shows and filters on; change them here, not in the
-- app. Line Status is where the line is with Medline, checked in this order:
--   rejected       Medline rejected the line: Bad Line = YES, or a Rej Code (E1, S1, X1; on the
--                  2026-10-07 sample these always came with Shipped 0)
--   not_confirmed  no 855 (Medline's order confirmation) yet
--   asn            Medline sent the ASN (856): it shipped
--   confirmed      confirmed, not shipped yet
-- The app labels them; a new status here needs its label in app/ordertiming/queries.py (STATUSES).
--
-- Short Qty (2026-11-17) is what the line is short shipped, apart from its status (the user: ASN
-- sent wins over short shipped in the status, and short shipped is tallied on its own): Order Qty
-- less Shipped Qty and Open Qty, when that's more than 0; NULL otherwise, and on a rejected line.
-- On FILL-KILL lines Medline ships what it has and kills the rest, so these are the lines in
-- Medline's Fill/Kill feed (on O2 on 11/17 every one found there matched on order, line and item).
-- Only once there's a delivery document: until then Shipped Qty isn't Medline's answer yet, so a
-- line just confirmed isn't short.
-- Medline's SAP delivery document isn't a status (the user, 2026-11-16): it only means the line
-- reached Medline's SAP, which says nothing about the order's timing. (Short Qty reads it only as
-- the sign that Shipped Qty is set.)
--
-- Times are as Medline sends them. The file's "Dates & Times Time Zone:" line is blank, and A13's
-- notes find its file stamps look like Central time: ask Medline before reading them as Eastern.
--
-- The app's account needs SELECT on SCSFileIngestor's MedlineOrderTiming.MedlineOrderTiming and
-- MedlineReport.ETLHealth (the second one Fill/Kill's go-live already granted): a view here doesn't
-- carry permissions into another database.

SET NOCOUNT ON;

IF SCHEMA_ID(N'OrderTiming') IS NULL
    EXEC (N'CREATE SCHEMA [OrderTiming] AUTHORIZATION [dbo];');
GO

CREATE OR ALTER VIEW [OrderTiming].[vw_MedlineOrderLine] AS
-- Every order line in Medline's feed, its source columns as A13 loads them (names as Medline spells
-- them, "EDI Date Re" and the double space in "Mins  to Order Create" included), then:
--   Received At          when Medline received the line by EDI (850)
--   Order Created At     when Medline created its sales order
--   Confirmed At         when Medline sent its 855 confirmation; empty until it does
--   ASN Created At       when Medline made the ASN (856)
--   Line Status          see the top of this script
--   Short Qty            the same
SELECT l.[Report Date], l.[Order Create Date], l.[Sold-To #], l.[Sold-To Name], l.[Ship-To #], l.[Ship-To Name],
       l.[Order #], l.[Channel], l.[PO#], l.[Buyer Name], l.[Cust Item #], l.[PO Line #], l.[Item # on PO],
       l.[Medline Item #], l.[Medline Category], l.[Mfr Item #], l.[Manufacturer], l.[Item Description],
       l.[Order Qty], l.[Open Qty], l.[Shipped Qty], l.[UM], l.[Bad Line], l.[Rej Code], l.[Line Type],
       l.[EDI Date Re], l.[EDI Data Recv Time], l.[Order Create Time], l.[855 Date], l.[855 Time],
       l.[Mins  to Order Create], l.[Mins to Confirm], l.[SAP Delv Doc #], l.[SAP Delv Doc Create Date],
       l.[SAP Delv Doc Create Time], l.[ASN Creation Date], l.[ASN Creation Time], l.[Branch], l.[Order Line],
       l.[Lot], l.[Expiration], l.[PO Type], l.[SCAC], l.[SortCode], l.[PO], l.[POLine], l.[ShipTo],
       l.[source file], l.[load stamp],
       t.[Received At], t.[Order Created At], t.[Confirmed At], t.[ASN Created At],
       CAST(CASE
           WHEN r.[Rejected] = 1                  THEN 'rejected'
           WHEN l.[855 Date] IS NULL              THEN 'not_confirmed'
           WHEN l.[ASN Creation Date] IS NOT NULL THEN 'asn'
           ELSE 'confirmed'
       END AS VARCHAR(20)) AS [Line Status],
       CASE WHEN r.[Rejected] = 0 AND l.[SAP Delv Doc #] IS NOT NULL
                 AND l.[Order Qty] > ISNULL(l.[Shipped Qty], 0) + ISNULL(l.[Open Qty], 0)
            THEN l.[Order Qty] - ISNULL(l.[Shipped Qty], 0) - ISNULL(l.[Open Qty], 0)
       END AS [Short Qty]
FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming] AS l
CROSS APPLY (SELECT CASE WHEN l.[Bad Line] = 'YES' OR NULLIF(LTRIM(RTRIM(l.[Rej Code])), '') IS NOT NULL
                         THEN 1 ELSE 0 END AS [Rejected]) AS r
-- A date and its time as one DATETIME (a missing time counts as midnight; no date, no value).
CROSS APPLY (SELECT
    CASE WHEN l.[EDI Date Re] IS NOT NULL
         THEN CAST(l.[EDI Date Re] AS DATETIME) + CAST(ISNULL(l.[EDI Data Recv Time], '00:00') AS DATETIME) END
        AS [Received At],
    CASE WHEN l.[Order Create Date] IS NOT NULL
         THEN CAST(l.[Order Create Date] AS DATETIME) + CAST(ISNULL(l.[Order Create Time], '00:00') AS DATETIME) END
        AS [Order Created At],
    CASE WHEN l.[855 Date] IS NOT NULL
         THEN CAST(l.[855 Date] AS DATETIME) + CAST(ISNULL(l.[855 Time], '00:00') AS DATETIME) END
        AS [Confirmed At],
    CASE WHEN l.[ASN Creation Date] IS NOT NULL
         THEN CAST(l.[ASN Creation Date] AS DATETIME) + CAST(ISNULL(l.[ASN Creation Time], '00:00') AS DATETIME) END
        AS [ASN Created At]
) AS t;
GO

CREATE OR ALTER VIEW [OrderTiming].[vw_OrderTimingLastLoad] AS
-- One row: the last successful A13 run ("Medline Order Timing" in ETLHealth), and when the newest
-- day's lines were loaded, which stands in until the scheduled runs are logged (the backfill doesn't
-- log). The app reads it on every search, so it reads the newest day only: Report Date leads the
-- table's clustered key, so that's a seek, not a scan of every day.
--   last_file   the file that run loaded (else the newest day's), whose name says when Medline made
--               it: "MHS - ORDER DETAIL REPORT-2026-11-17-01-02-15.xls", Central time on a 12-hour
--               clock. The app reads it as the page's "Data as of" (app/utility/freshness.py), and
--               the load as "Last loaded" (2026-11-17). Optional: without it, the app shows only
--               "Last loaded".
SELECT r.[LastRunTime] AS [last_success], l.[load stamp] AS [last_line_load],
       COALESCE(r.[SourceFilePath], l.[source file]) AS [last_file]
FROM (VALUES (1)) AS one ([row])
OUTER APPLY (SELECT TOP (1) h.[LastRunTime], h.[SourceFilePath]
             FROM [SCSFileIngestor].[MedlineReport].[ETLHealth] AS h
             WHERE h.[ProcessName] = 'Medline Order Timing' AND h.[TaskStatus] = 'SUCCESS'
             ORDER BY h.[LastRunTime] DESC) AS r
OUTER APPLY (SELECT TOP (1) m.[load stamp], m.[source file]
             FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming] AS m
             WHERE m.[Report Date] = (SELECT MAX([Report Date])
                                      FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming])
             ORDER BY m.[load stamp] DESC) AS l;
GO

-- What's there now: one row per Line Status (and how many of its lines are short shipped), then the
-- freshness row. Every Line Status should be one of the four above.
SELECT [Line Status], COUNT(*) AS [lines], COUNT(DISTINCT [Order #]) AS [orders],
       COUNT([Short Qty]) AS [short shipped lines],
       MIN([Report Date]) AS [first day], MAX([Report Date]) AS [last day]
FROM [OrderTiming].[vw_MedlineOrderLine]
GROUP BY [Line Status]
ORDER BY [Line Status];

SELECT [last_success], [last_line_load], [last_file] FROM [OrderTiming].[vw_OrderTimingLastLoad];
GO

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the objects it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those objects. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO

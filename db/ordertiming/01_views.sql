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
--                                        as one value and the line's status (Line Status)
--   OrderTiming.vw_OrderTimingLastLoad   one row: how fresh the lines are, for the app's "data as of"
--
-- Line Status is the rule the app shows and filters on; change it here, not in the app. Checked in
-- this order:
--   rejected       Medline rejected the line: Bad Line = YES, or a Rej Code (E1, S1, X1; on the
--                  2026-10-07 sample these always came with Shipped 0)
--   not_confirmed  no 855 (Medline's order confirmation) yet
--   asn            Medline sent the ASN (856): it shipped
--   confirmed      confirmed, not shipped yet
-- Medline's SAP delivery document isn't a status (the user, 2026-11-16): it only means the line
-- reached Medline's SAP, which says nothing about the order's timing.
-- The app labels them; a new status here needs its label in app/ordertiming/queries.py (STATUSES).
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
           WHEN l.[Bad Line] = 'YES' OR NULLIF(LTRIM(RTRIM(l.[Rej Code])), '') IS NOT NULL THEN 'rejected'
           WHEN l.[855 Date] IS NULL                                                          THEN 'not_confirmed'
           WHEN l.[ASN Creation Date] IS NOT NULL                                             THEN 'asn'
           ELSE 'confirmed'
       END AS VARCHAR(20)) AS [Line Status]
FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming] AS l
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
SELECT (SELECT MAX([LastRunTime]) FROM [SCSFileIngestor].[MedlineReport].[ETLHealth]
        WHERE [ProcessName] = 'Medline Order Timing' AND [TaskStatus] = 'SUCCESS') AS [last_success],
       (SELECT MAX(l.[load stamp]) FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming] AS l
        WHERE l.[Report Date] = (SELECT MAX([Report Date])
                                 FROM [SCSFileIngestor].[MedlineOrderTiming].[MedlineOrderTiming])) AS [last_line_load];
GO

-- What's there now: one row per Line Status, then the freshness row. Every Line Status should be
-- one of the four above.
SELECT [Line Status], COUNT(*) AS [lines], COUNT(DISTINCT [Order #]) AS [orders],
       MIN([Report Date]) AS [first day], MAX([Report Date]) AS [last day]
FROM [OrderTiming].[vw_MedlineOrderLine]
GROUP BY [Line Status]
ORDER BY [Line Status];

SELECT [last_success], [last_line_load] FROM [OrderTiming].[vw_OrderTimingLastLoad];
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

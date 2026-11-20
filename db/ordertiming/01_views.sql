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
--   OrderTiming.vw_ShortShipLine         Short Ships' lines: the short-shipped ones, each with its
--                                        PO's total lines, its line in Fill/Kill's feed and
--                                        (2026-11-18) its QOE from Infor, with its quantities in eaches
--   OrderTiming.vw_ItemKillDay           Short Ships' kill counts: Fill/Kill's kill lines per item,
--                                        Sold-To and day (and, 2026-11-20, UM and ship-to code,
--                                        with what they killed)
--   OrderTiming.vw_OrderTimingLastLoad   one row: how fresh the lines are, for the app's "Data as
--                                        of" (Medline's file) and "Last loaded"
--
-- The two Short Ships views (2026-11-17) read Fill/Kill's FillKill.vw_MedlineFillKill, so run
-- db/fillkill/10 before this script on a new database. They join the two feeds here, not in the app.
-- vw_ShortShipLine's QOE (2026-11-18) reads Infor's tables in PLMPreprocessorShared, as Fill/Kill's
-- 11 does.
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

CREATE OR ALTER VIEW [OrderTiming].[vw_ShortShipLine] AS
-- Short Ships' lines (2026-11-17): every short-shipped line (a Short Qty, whatever its status) with
-- all of vw_MedlineOrderLine's columns (re-created right after it, so it has them all), then:
--   PO Total Lines     the lines on its PO that day, short or not (Main's Total lines)
--   In Fill/Kill       1 when Medline's Fill/Kill feed has the line, else 0: the same Medline order
--                      and order line, which both feeds write alike since A13's fix of 11/17 (on O2
--                      that day, all 106 Fill/Kill lines on our orders matched). A line just shorted
--                      may not be in it yet: the two feeds come in their own files.
--   Fill/Kill Reason   Medline's reason type for the kill (FillKill.vw_MedlineFillKill's Reason)
--   Est Avail Date     its Est Avail Date (that view's Reason Date)
--   InforUOM           (2026-11-18) the line's UM as Infor calls it, as vw_MedlineFillKill has it:
--                      through Infor's EDI list (MDM_EDI_SUB_UOM: CS is CA, BT is BO, TR is TY),
--                      else as Medline writes it
--   QOE                (2026-11-18) eaches in one of the line's UM: Infor's UOM conversion for that
--                      InforUOM of the Medline item's Infor item, found by Medline vendor item, as
--                      Fill/Kill's item view finds it (never by manufacturer part: different makers
--                      share simple part numbers). An EA without one is 1. NULL when Infor has none,
--                      or two Infor items disagree. On O2 (11/18) all 185 short lines of the last 30
--                      days had one, the same as Fill/Kill's item view gives their items.
--                      Read from Infor's tables here rather than from that view: it knows only items
--                      that have been in Fill/Kill's feed (a line shorted before its kill line comes
--                      in, or on an STD order, wouldn't have one), and it has a row per sub.
--   Order Qty EA       Order Qty in eaches (Order Qty x QOE); NULL without a QOE
--   Short Qty EA       Short Qty in eaches, the same way
-- The PO's lines are counted before the short ones are picked, over its day, Sold-To and order: the
-- columns the app filters on, so its days and sites still reach the source table's key (on O2,
-- 11/17, with the days as parameters: a range with no lines was a seek reading none).
-- The app's account reads Infor's tables already (Fill/Kill's go-live granted MDM_VENDORITEM,
-- MDM_ITEMUOM and MDM_EDI_SUB_UOM in PLMPreprocessorShared).
SELECT l.*,
       CAST(CASE WHEN k.[Sales Order #] IS NULL THEN 0 ELSE 1 END AS BIT) AS [In Fill/Kill],
       k.[Reason] AS [Fill/Kill Reason], k.[Reason Date] AS [Est Avail Date],
       u.[InforUOM], q.[QOE], l.[Order Qty] * q.[QOE] AS [Order Qty EA], l.[Short Qty] * q.[QOE] AS [Short Qty EA]
FROM (SELECT o.*, COUNT(*) OVER (PARTITION BY o.[Report Date], o.[Sold-To #], o.[Order #]) AS [PO Total Lines]
      FROM [OrderTiming].[vw_MedlineOrderLine] AS o) AS l
LEFT JOIN [FillKill].[vw_MedlineFillKill] AS k
       ON k.[Sales Order #] = l.[Order #] AND k.[Order Line #] = l.[Order Line]
-- InforUOM as vw_MedlineFillKill makes it (one row per external value, so no line is repeated).
LEFT JOIN [PLMPreprocessorShared].[infor].[MDM_EDI_SUB_UOM] AS uom
       ON uom.[ExternalValue] = l.[UM]
CROSS APPLY (SELECT COALESCE(uom.[LawsonValue], l.[UM]) AS [InforUOM]) AS u
-- The Infor item's conversion for it (Fill/Kill's item view's CTEs f and b), taken only when every
-- Infor item found has the same one.
OUTER APPLY (SELECT CASE WHEN COUNT(DISTINCT iu.[UOMConversion]) = 1 THEN MIN(iu.[UOMConversion]) END AS [conversion]
             FROM [PLMPreprocessorShared].[infor].[MDM_VENDORITEM] AS vi
             JOIN [PLMPreprocessorShared].[infor].[MDM_ITEMUOM] AS iu
                  ON iu.[Item] = vi.[Item] AND iu.[UOM] = u.[InforUOM]
             WHERE vi.[VendorItem] = l.[Medline Item #] AND vi.[VendorName] LIKE '%Medline%'
               AND vi.[Active] = 'Yes') AS c
CROSS APPLY (SELECT COALESCE(c.[conversion], CASE WHEN u.[InforUOM] = 'EA' THEN 1 END) AS [QOE]) AS q
WHERE l.[Short Qty] > 0;
GO

CREATE OR ALTER VIEW [OrderTiming].[vw_ItemKillDay] AS
-- How often Medline's Fill/Kill feed killed each item (2026-11-17), for Short Ships' kill counts:
-- the kill lines per Medline item, Sold-To and Order Date. Sold-To # is as Medline's Order Detail
-- feed writes it, ten digits with the leading zeros, which Fill/Kill's file drops (its 2159659 is
-- 0002159659), so the app filters both with the same site codes. The app adds up the days it shows
-- (today, the last 7 and the last 30).
-- 2026-11-20 (the user: how much, and how many requesting locations, beside the lines): also per UM
-- and Ship-To Code, with [Killed Qty], what the lines killed. As Fill/Kill counts them: Order Qty less
-- Filled Qty, in Medline's UM; the Ship-To Code is Fill/Kill's (10: Ship-To Name 2 up to its hyphen,
-- PMOSN1RO). The app adds up the lines and the quantity per UM, and counts each ship-to code once.
-- The release before reads only [Kill Lines], which it adds up per item, so it reads this the same.
SELECT k.[Item] AS [Medline Item #], s.[Sold-To #], k.[Order Date], k.[UM], k.[Ship-To Code],
       COUNT(*) AS [Kill Lines],
       SUM(COALESCE(k.[Order Qty], 0) - COALESCE(k.[Filled Qty], 0)) AS [Killed Qty]
FROM [FillKill].[vw_MedlineFillKill] AS k
CROSS APPLY (SELECT LTRIM(RTRIM(k.[Sold-To])) AS [code]) AS c
CROSS APPLY (SELECT CASE WHEN c.[code] NOT LIKE '%[^0-9]%' AND LEN(c.[code]) BETWEEN 1 AND 9
                         THEN RIGHT('0000000000' + c.[code], 10)
                         ELSE c.[code] END AS [Sold-To #]) AS s
GROUP BY k.[Item], s.[Sold-To #], k.[Order Date], k.[UM], k.[Ship-To Code];
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

-- Short Ships: the short-shipped lines, how many Fill/Kill has (the rest came in a newer file than
-- Fill/Kill's last), and how many have a QOE (the rest show no eaches; on O2, 11/18, all of them).
SELECT COUNT(*) AS [short shipped lines], SUM(CAST([In Fill/Kill] AS INT)) AS [in Fill/Kill],
       COUNT([QOE]) AS [with a QOE]
FROM [OrderTiming].[vw_ShortShipLine];

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

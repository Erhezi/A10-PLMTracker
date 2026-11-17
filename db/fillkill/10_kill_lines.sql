-- Kill lines for the Fill/Kill module.
-- Run on O2, database PLM. Safe to re-run: it (re)creates two views and drops the old test-line
-- table, if it's still there and empty.
--
-- FillKill.vw_MedlineFillKill is the one place the module reads kill lines from: Medline's table
-- in SCSFileIngestor (written only by the A13 ingestion). FillKill.vw_FillKillLastLoad says how
-- fresh they are, for the app's "Data as of" (when Medline made the file) and "Last loaded".
--
-- 2026-11-17: vw_FillKillLastLoad has [last_file], the file loaded, for "Data as of". The app reads
-- it when it's there, so [last_file] doesn't decide when this script runs; [Is Test] does (below:
-- after the deploy).
--
-- 2026-11-16, real data: Medline's final file carries its own reason type ([ReasonTypeText]),
-- which is now the Reason as Medline sends it, instead of a category we read from the comment;
-- its [Est Avail Date] is the Reason Date, instead of the first date in the comment; and the
-- view gives the ship-to's location code (Ship-To Name 2 without '- UBOAT'), the name Materials
-- Managers know. The test lines are gone (the user emptied FillKill.TestFillKillLine).
--
-- Later the same day: the view no longer has [Is Test] and [Test Purpose] (kept until then as 0
-- and NULL), and this script drops FillKill.TestFillKillLine. RUN THIS VERSION AFTER THE DEPLOY
-- of the release that stopped reading them: the release before it reads [Is Test] to open an
-- item's panel. The version run on O2 before the deploy (2026-11-16 21:55) works with both.

SET NOCOUNT ON;
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKill] AS
-- Every kill line the module shows: Medline's.
--   Reason        Medline's reason type, as sent ([ReasonTypeText]: Allocated Item, Backorder,
--                 Custom, Non-Stock, Disco`d, ...); NULL when empty
--   Reason Date   Medline's [Est Avail Date], as sent (2026-11-16; it was the first date in the
--                 comment). Allocated Item lines have one too, the comment none.
--   Ship-To Code  Ship-To Name 2 up to its first hyphen, trimmed: 'PMOSN1RO - UBOAT' gives PMOSN1RO
SELECT m.[Sold-To], m.[Sold-To Name], m.[Ship-To], m.[Ship-To Name], m.[Ship-To Name 2],
       m.[Order Date], m.[Order Time], m.[PO #], m.[PO Line], m.[Sales Order #], m.[Order Line #],
       m.[Item], m.[Item Description], m.[Item # on PO], m.[Customer Item #], m.[Mfr. Item #],
       m.[Manufacturer Name], m.[Order Qty], m.[UM], m.[Filled Qty], m.[Plant], m.[Buyer Name],
       m.[Internal Order Comments from SAP (Z106)], m.[PO], m.[POLine], m.[source file],
       m.[create stamp], m.[update stamp],
       -- Medline's final file (2026-11-16)
       m.[ReasonTypeText], m.[MBO Type Description], m.[Est Avail Date],
       m.[Product Allocation Qty], m.[Open Product Allocation Qty], m.[PA Fulfill Flag],
       m.[Allocation Period Type], m.[Allocation Level], m.[Possible Subst. Item],
       m.[Customer Preferred Substitute Item], m.[DED Qty], m.[DED UOM Code], m.[DED Valid From Date],
       m.[Forecast Qty], m.[30 Day Delivered Qty],
       NULLIF(LTRIM(RTRIM(m.[ReasonTypeText])), '') AS [Reason],
       m.[Est Avail Date] AS [Reason Date],
       NULLIF(LTRIM(RTRIM(LEFT(m.[Ship-To Name 2],
           CHARINDEX('-', m.[Ship-To Name 2] + '-') - 1))), '') AS [Ship-To Code]
FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill] AS m;
GO

CREATE OR ALTER VIEW [FillKill].[vw_FillKillLastLoad] AS
-- One row: the last successful A13 run ("Medline Fill-Kill" in ETLHealth), and the newest line
-- update, which stands in until the hourly runs are logged (the backfill doesn't log).
--   last_file   the file that run loaded (else the newest line's), whose name says when Medline made
--               it: "MHS - FILL KILL REPORT-2026-11-17-01-04-00.xlsx", Central time on a 12-hour
--               clock. The app reads it as the page's "Data as of" (app/utility/freshness.py), and
--               the load as "Last loaded" (2026-11-17). Optional: without it, the app shows only
--               "Last loaded".
SELECT r.[LastRunTime] AS [last_success], l.[update stamp] AS [last_line_update],
       COALESCE(r.[SourceFilePath], l.[source file]) AS [last_file]
FROM (VALUES (1)) AS one ([row])
OUTER APPLY (SELECT TOP (1) h.[LastRunTime], h.[SourceFilePath]
             FROM [SCSFileIngestor].[MedlineReport].[ETLHealth] AS h
             WHERE h.[ProcessName] = 'Medline Fill-Kill' AND h.[TaskStatus] = 'SUCCESS'
             ORDER BY h.[LastRunTime] DESC) AS r
OUTER APPLY (SELECT TOP (1) m.[update stamp], m.[source file]
             FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill] AS m
             ORDER BY m.[update stamp] DESC) AS l;
GO

-- The test lines' table (2026-11-16): emptied, and read by nothing. Dropped only when empty, so
-- lines someone put back aren't lost.
IF OBJECT_ID(N'[FillKill].[TestFillKillLine]', N'U') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM [FillKill].[TestFillKillLine])
        RAISERROR('FillKill.TestFillKillLine has lines again, so it was not dropped. Empty it (TRUNCATE TABLE [FillKill].[TestFillKillLine];) and re-run this script.', 16, 1);
    ELSE
        DROP TABLE [FillKill].[TestFillKillLine];
END;
GO

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the objects it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those tables. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO

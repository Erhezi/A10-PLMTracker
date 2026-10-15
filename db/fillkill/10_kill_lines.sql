-- Kill lines for the Fill/Kill module: Medline's lines plus test copies under a fake site.
-- Run on O2, database PLM. No app deploy needed. Safe to re-run: it reloads the test copies.
--
-- FillKill.vw_MedlineFillKill is the one place the module reads kill lines from: Medline's table
-- in SCSFileIngestor (written only by the A13 ingestion), plus FillKill.TestFillKillLine.
-- FillKill.vw_FillKillLastLoad says how fresh they are, for the app's "data as of".
--
-- Test lines, all under Sold-To 'test site', with 'TEST' at the start of the Sales Order # so they
-- never clash with a real line. [Test Purpose] says why each line is there:
--   - Sites: for each of the latest 3 order dates in Medline's data, the last 10 lines of the day
--     (by order time), copied as Medline sent them (item, quantities, comment, PO).
--   - Many Medline items to one Infor item (hand-made): other Medline items of Infor items 111848
--     and 101494, in other UOMs, on 9/28-9/30. They copy a real line of the same Infor item and
--     change the Medline item, UOM, quantity and (for 111848) the comment; PO is left empty.
--   - Customer item isn't the Infor item (hand-made, 9/30): DYNJAA04 under customer item
--     1296-DYNJAA04 (an Infor contract-only number), B-D930299H under itself (not a Medline vendor
--     item in Infor), and B-D367344 under 198765 (not in Infor; the vendor item is 102205). Given
--     in full; ship-to, plant and buyer copy the latest real line.
--   - Contract search, MHS or not (hand-made, 9/30): BXT2D0737H (EA, Infor item 112057), on
--     Medline JIT contracts that are and aren't MHS's. Given in full, like the ones above.
-- Re-running deletes and reloads them all.
--
-- At go-live, remove them:  TRUNCATE TABLE [FillKill].[TestFillKillLine];

SET NOCOUNT ON;

IF OBJECT_ID(N'[FillKill].[TestFillKillLine]', N'U') IS NULL
BEGIN
    -- Same columns as SCSFileIngestor.MedlineFillKill.MedlineFillKill.
    CREATE TABLE [FillKill].[TestFillKillLine] (
        [Sold-To]                                 VARCHAR(20)   NULL,
        [Sold-To Name]                            VARCHAR(100)  NULL,
        [Ship-To]                                 VARCHAR(20)   NULL,
        [Ship-To Name]                            VARCHAR(100)  NULL,
        [Ship-To Name 2]                          VARCHAR(100)  NULL,
        [Order Date]                              DATE          NULL,
        [Order Time]                              TIME(0)       NULL,
        [PO #]                                    VARCHAR(50)   NULL,
        [PO Line]                                 VARCHAR(10)   NULL,
        [Sales Order #]                           VARCHAR(20)   NOT NULL,
        [Order Line #]                            VARCHAR(10)   NOT NULL,
        [Item]                                    VARCHAR(50)   NULL,
        [Item Description]                        VARCHAR(255)  NULL,
        [Item # on PO]                            VARCHAR(50)   NULL,
        [Customer Item #]                         VARCHAR(50)   NULL,
        [Mfr. Item #]                             VARCHAR(100)  NULL,
        [Manufacturer Name]                       VARCHAR(100)  NULL,
        [Order Qty]                               INT           NULL,
        [UM]                                      VARCHAR(10)   NULL,
        [Filled Qty]                              INT           NULL,
        [Plant]                                   VARCHAR(10)   NULL,
        [Buyer Name]                              VARCHAR(100)  NULL,
        [Internal Order Comments from SAP (Z106)] VARCHAR(1000) NULL,
        [PO]                                      VARCHAR(10)   NULL,
        [POLine]                                  INT           NULL,
        [source file]                             VARCHAR(260)  NULL,
        [create stamp]                            DATETIME      NOT NULL,
        [update stamp]                            DATETIME      NOT NULL,
        [Test Purpose]                            VARCHAR(300)  NULL,  -- why the line is here
        CONSTRAINT [PK_TestFillKillLine] PRIMARY KEY CLUSTERED ([Sales Order #], [Order Line #])
    );
    PRINT 'Created FillKill.TestFillKillLine';
END;
GO

IF COL_LENGTH(N'FillKill.TestFillKillLine', N'Test Purpose') IS NULL
BEGIN
    ALTER TABLE [FillKill].[TestFillKillLine] ADD [Test Purpose] VARCHAR(300) NULL;
    PRINT 'Added TestFillKillLine.[Test Purpose]';
END;
GO

DECLARE @days INT = 3, @lines_per_day INT = 10;
DECLARE @sites VARCHAR(300) = 'Sites: a real line copied under a second site, to test combining sites '
    + '(site filter, per-site and all-site totals).';
DECLARE @many_111848 VARCHAR(300) = 'Many Medline items to one Infor item: JLCSFTP22A5S (BX) beside '
    + 'JLCSFTP22A5SH (EA), both 111848. Also different reasons on one Infor item: MBO here, NONSTOCK UOM '
    + 'on JLCSFTP22A5SH.';
DECLARE @many_101494 VARCHAR(300) = 'Many Medline items to one Infor item: J-J2015 (CA) and J-J2015Z (BX) '
    + 'beside J-J2015H (EA), all 101494, in three UOMs.';
DECLARE @customer_dynjaa04 VARCHAR(300) = 'Customer item is not an Infor item: 1296-DYNJAA04 is Infor''s '
    + 'contract-only (Special) number, manufacturer code 1296 + Medline item. No item master record, so '
    + 'it stands alone, flagged.';
DECLARE @customer_bd930299h VARCHAR(300) = 'Customer item is the Medline item itself (B-D930299H), which '
    + 'isn''t a Medline vendor item in Infor (Infor item 100091 has B-D930299 CA and B-D930299Z BX). No '
    + 'Infor item, so it stands alone, flagged.';
DECLARE @customer_bd367344 VARCHAR(300) = 'Customer item is a number, but not the Infor item: 198765 isn''t in '
    + 'Infor''s item master, while Medline vendor item B-D367344 is Infor item 102205 (CA = 200 EA).';
DECLARE @contract_bxt2d0737h VARCHAR(300) = 'Contract search MHS / Non-MHS: BXT2D0737H (EA, Infor item 112057) is '
    + 'on Medline JIT contracts 1412 and 2421 (not MHS) and 2680 (MHS, from 10/01/2026); BXT2D0737 (CA) also '
    + 'on Medline contract 2632 (MHS).';

BEGIN TRANSACTION;

DELETE FROM [FillKill].[TestFillKillLine];

WITH days AS (
    SELECT DISTINCT TOP (@days) [Order Date]
    FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill]
    ORDER BY [Order Date] DESC
),
ranked AS (
    SELECT m.*,
           ROW_NUMBER() OVER (PARTITION BY m.[Order Date]
                              ORDER BY m.[Order Time] DESC, m.[Sales Order #] DESC, m.[Order Line #] DESC) AS [rk]
    FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill] AS m
    JOIN days AS d ON d.[Order Date] = m.[Order Date]
)
INSERT INTO [FillKill].[TestFillKillLine] (
    [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
    [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
    [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
    [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
    [create stamp], [update stamp], [Test Purpose]
)
SELECT 'test site', 'test site', [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
       [PO #], [PO Line], 'TEST' + [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
       [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
       [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
       GETDATE(), GETDATE(), @sites
FROM ranked
WHERE [rk] <= @lines_per_day;

PRINT CONCAT('Test lines loaded (sites): ', @@ROWCOUNT);

-- Hand-made lines: each copies the latest real line of the same Infor item (customer item) and
-- changes what's listed here. A NULL comment keeps the real line's comment.
INSERT INTO [FillKill].[TestFillKillLine] (
    [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
    [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
    [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
    [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
    [create stamp], [update stamp], [Test Purpose]
)
SELECT 'test site', 'test site', t.[Ship-To], t.[Ship-To Name], t.[Ship-To Name 2], v.[order_date], '12:00:00',
       NULL, NULL, v.[sales_order], '000010', v.[item], t.[Item Description], v.[item],
       t.[Customer Item #], t.[Mfr. Item #], t.[Manufacturer Name], v.[qty], v.[um], 0, t.[Plant],
       t.[Buyer Name], COALESCE(v.[comment], t.[Internal Order Comments from SAP (Z106)]), NULL, NULL,
       'hand-made test line (10_kill_lines.sql)', GETDATE(), GETDATE(), v.[purpose]
FROM (VALUES
    ('TEST-111848-0928', CAST('2026-09-28' AS DATE), 'JLCSFTP22A5S', 'BX', 5,  'MBO - ERD is 11/10/2026', '111848', @many_111848),
    ('TEST-111848-0929', CAST('2026-09-29' AS DATE), 'JLCSFTP22A5S', 'BX', 5,  'MBO - ERD is 11/10/2026', '111848', @many_111848),
    ('TEST-111848-0930', CAST('2026-09-30' AS DATE), 'JLCSFTP22A5S', 'BX', 5,  'MBO - ERD is 11/10/2026', '111848', @many_111848),
    ('TEST-101494-0930', CAST('2026-09-30' AS DATE), 'J-J2015',      'CA', 10, NULL,                      '101494', @many_101494),
    ('TEST-101494-0929', CAST('2026-09-29' AS DATE), 'J-J2015Z',     'BX', 4,  NULL,                      '101494', @many_101494)
) AS v ([sales_order], [order_date], [item], [um], [qty], [comment], [customer_item], [purpose])
CROSS APPLY (
    SELECT TOP (1) m.*
    FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill] AS m
    WHERE m.[Customer Item #] = v.[customer_item]
    ORDER BY m.[Order Date] DESC, m.[Order Time] DESC
) AS t;

PRINT CONCAT('Test lines loaded (many Medline items to one Infor item): ', @@ROWCOUNT);

-- Hand-made lines given in full: customer items that aren't the Infor item, and the contract
-- search's MHS indicator. Everything Medline would send is given here (no PO for B-D367344 or
-- BXT2D0737H; BXT2D0737H's description and manufacturer are Infor's contract line's); ship-to,
-- plant and buyer copy the latest real line.
INSERT INTO [FillKill].[TestFillKillLine] (
    [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
    [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
    [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
    [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
    [create stamp], [update stamp], [Test Purpose]
)
SELECT 'test site', 'test site', t.[Ship-To], t.[Ship-To Name], t.[Ship-To Name 2], v.[order_date], '12:30:00',
       v.[po], v.[po_line], v.[sales_order], '000010', v.[item], v.[description], v.[customer_item],
       v.[customer_item], v.[mfr_item], v.[manufacturer], v.[qty], v.[um], v.[filled], t.[Plant],
       t.[Buyer Name], v.[comment], v.[po], CAST(v.[po_line] AS INT),
       'hand-made test line (10_kill_lines.sql)', GETDATE(), GETDATE(), v.[purpose]
FROM (VALUES
    ('TEST-DYNJAA04-0930',  CAST('2026-09-30' AS DATE), 'DYNJAA04',   '1296-DYNJAA04',
     'LINE GAS SMPL M TO M LL CNCT 10FT .06MM LF', 'DYNJAA04', 'MEDLINE', '2400134117', '1', 'CA', 5, 2,
     'Allocation limit has been reached', @customer_dynjaa04),
    ('TEST-BD930299H-0930', CAST('2026-09-30' AS DATE), 'B-D930299H', 'B-D930299H',
     'Skin Prep Swabs: ChloraPrep FREPP Applicator, Clear, with St', '930299', 'BD', '2624108620', '27', 'EA', 30, 15,
     'Allocation limit has been reached', @customer_bd930299h),
    ('TEST-BD367344-0930',  CAST('2026-09-30' AS DATE), 'B-D367344',  '198765',
     'MBO-SET,BLOOD COLL,21G X .75",VACUTAINER', '367344', 'BD', NULL, NULL, 'CA', 3, 0,
     'MBO - ERD is 11/30/2026', @customer_bd367344),
    ('TEST-BXT2D0737H-0930', CAST('2026-09-30' AS DATE), 'BXT2D0737H', '112057',
     'SOLUTION INHL H2O 2000ML FLXB BG CNTNR STRL LF ARLF', '2D0737', 'AIRLIFE', NULL, NULL, 'EA', 5, 0,
     'MBO - ERD is 11/30/2026', @contract_bxt2d0737h)
) AS v ([sales_order], [order_date], [item], [customer_item], [description], [mfr_item], [manufacturer], [po],
        [po_line], [um], [qty], [filled], [comment], [purpose])
CROSS APPLY (
    SELECT TOP (1) m.*
    FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill] AS m
    ORDER BY m.[Order Date] DESC, m.[Order Time] DESC
) AS t;

PRINT CONCAT('Test lines loaded (given in full): ', @@ROWCOUNT);

COMMIT TRANSACTION;
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKill] AS
-- Every kill line the module shows: Medline's, plus the test lines until go-live.
--   Test Purpose why a test line is there (NULL on Medline's lines)
--   Reason       category of Medline's comment, checked in this order (a comment can match more
--                than one word; e.g. "SPIKE - Allocation limit..." counts as ALLOCATION)
--   Reason Date  the first mm/dd/yyyy date in the comment (the ERD or ETA), if any
SELECT l.*,
       CASE
           WHEN NULLIF(LTRIM(c.[comment]), '') IS NULL THEN NULL
           WHEN c.[comment] LIKE '%NONSTOCK UOM%' THEN 'NONSTOCK_UOM'
           WHEN c.[comment] LIKE '%NONSTOCK%'     THEN 'NONSTOCK'
           WHEN c.[comment] LIKE '%DISCONTINUED%' THEN 'DISCONTINUED'
           WHEN c.[comment] LIKE '%Allocation%'   THEN 'ALLOCATION'
           WHEN c.[comment] LIKE '%SPIKE%'        THEN 'SPIKE'
           WHEN c.[comment] LIKE '%MBO%'          THEN 'MBO'
           WHEN c.[comment] LIKE '%OUT OF STOCK%' THEN 'OUT_OF_STOCK'
           ELSE 'OTHER'
       END AS [Reason],
       TRY_CONVERT(DATE, SUBSTRING(c.[comment],
           NULLIF(PATINDEX('%[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]%', c.[comment]), 0), 10), 101) AS [Reason Date]
FROM (
    SELECT [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
           [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
           [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
           [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
           [create stamp], [update stamp],
           CAST(0 AS BIT) AS [Is Test], CAST(NULL AS VARCHAR(300)) AS [Test Purpose]
    FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill]
    UNION ALL
    SELECT [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
           [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
           [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
           [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
           [create stamp], [update stamp],
           CAST(1 AS BIT) AS [Is Test], [Test Purpose]
    FROM [FillKill].[TestFillKillLine]
) AS l
CROSS APPLY (SELECT l.[Internal Order Comments from SAP (Z106)] AS [comment]) AS c;
GO

CREATE OR ALTER VIEW [FillKill].[vw_FillKillLastLoad] AS
-- One row: the last successful A13 run ("Medline Fill-Kill" in ETLHealth), and the newest line
-- update, which stands in until the hourly runs are logged (the backfill doesn't log).
SELECT (SELECT MAX([LastRunTime]) FROM [SCSFileIngestor].[MedlineReport].[ETLHealth]
        WHERE [ProcessName] = 'Medline Fill-Kill' AND [TaskStatus] = 'SUCCESS') AS [last_success],
       (SELECT MAX([update stamp]) FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill]) AS [last_line_update];
GO

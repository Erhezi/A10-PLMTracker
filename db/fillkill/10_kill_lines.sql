-- Kill lines for the Fill/Kill module: Medline's lines plus test copies under a fake site.
-- Run on O2, database PLM. No app deploy needed. Safe to re-run: it reloads the test copies.
--
-- FillKill.vw_MedlineFillKill is the one place the module reads kill lines from: Medline's table
-- in SCSFileIngestor (written only by the A13 ingestion), plus FillKill.TestFillKillLine.
--
-- Test copies, for trying the module with more than one site: for each of the latest 3 order
-- dates in Medline's data, the last 10 lines of the day (by order time) are copied with Sold-To
-- and Sold-To Name set to 'test site', and 'TEST' in front of the Sales Order # so a copy never
-- clashes with a real line. Everything else (item, quantities, comment, PO) is as Medline sent it.
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
        CONSTRAINT [PK_TestFillKillLine] PRIMARY KEY CLUSTERED ([Sales Order #], [Order Line #])
    );
    PRINT 'Created FillKill.TestFillKillLine';
END;
GO

DECLARE @days INT = 3, @lines_per_day INT = 10;

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
    [create stamp], [update stamp]
)
SELECT 'test site', 'test site', [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
       [PO #], [PO Line], 'TEST' + [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
       [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
       [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
       GETDATE(), GETDATE()
FROM ranked
WHERE [rk] <= @lines_per_day;

PRINT CONCAT('Test lines loaded: ', @@ROWCOUNT);

COMMIT TRANSACTION;
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKill] AS
-- Every kill line the module shows: Medline's, plus the test copies until go-live.
SELECT [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
       [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
       [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
       [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
       [create stamp], [update stamp],
       CAST(0 AS BIT) AS [Is Test]
FROM [SCSFileIngestor].[MedlineFillKill].[MedlineFillKill]
UNION ALL
SELECT [Sold-To], [Sold-To Name], [Ship-To], [Ship-To Name], [Ship-To Name 2], [Order Date], [Order Time],
       [PO #], [PO Line], [Sales Order #], [Order Line #], [Item], [Item Description], [Item # on PO],
       [Customer Item #], [Mfr. Item #], [Manufacturer Name], [Order Qty], [UM], [Filled Qty], [Plant],
       [Buyer Name], [Internal Order Comments from SAP (Z106)], [PO], [POLine], [source file],
       [create stamp], [update stamp],
       CAST(1 AS BIT) AS [Is Test]
FROM [FillKill].[TestFillKillLine];
GO

-- Medline PBO subs: FillKill.usp_SyncPboSubs adds a sub for every Medline PBO substitute of a
-- killed item that isn't a sub yet. Run on O2, database PLM, after 11, 12 and 13, BEFORE deploy #2
-- (plan v2 §4.3, P6). Safe to re-run.
--
-- The app calls it each time the main table loads. It is set-based and idempotent, and never
-- touches an existing sub. A sub it adds:
--   vendor 'Medline', vendor part = the substitute number, status 'pending_review',
--   source 'medline_pbo', entered by 'Medline'; description, UOM and QOE from Medline's
--   contract line for that part when its lines agree on one UOM and QOE.
-- Each gets a 'created' History row. Returns the number of subs added.

SET NOCOUNT ON;
GO

CREATE OR ALTER PROCEDURE [FillKill].[usp_SyncPboSubs]
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @now DATETIME = GETDATE();
    DECLARE @added TABLE ([sub_id] INT, [medline_item] VARCHAR(50));

    BEGIN TRANSACTION;

    -- One caller at a time, so two page loads can't add the same sub; a caller that waits
    -- longer than 5 seconds gives up and adds nothing (the other caller is adding them).
    DECLARE @lock INT;
    EXEC @lock = sp_getapplock @Resource = N'FillKill.usp_SyncPboSubs', @LockMode = N'Exclusive',
                               @LockOwner = N'Transaction', @LockTimeout = 5000;
    IF @lock < 0
    BEGIN
        ROLLBACK TRANSACTION;
        SELECT 0 AS [added];
        RETURN;
    END;

    WITH pbo AS (
        SELECT DISTINCT [Medline Item] AS [medline_item], [Medline.Sub] AS [vendor_part]
        FROM [FillKill].[vw_MedlineFillKillItemCollection]
        WHERE NULLIF(LTRIM([Medline.Sub]), '') IS NOT NULL
    ),
    new_pbo AS (
        SELECT p.[medline_item], p.[vendor_part]
        FROM pbo AS p
        WHERE NOT EXISTS (
            SELECT 1 FROM [FillKill].[Sub] AS s
            WHERE s.[medline_item] = p.[medline_item] AND s.[vendor] = 'Medline'
              AND s.[vendor_part] = p.[vendor_part]
        )
    ),
    contract AS (
        SELECT cl.[vendor_item], MAX(cl.[description]) AS [description],
               MAX(cl.[uom]) AS [uom], MAX(cl.[qoe]) AS [qoe]
        FROM [FillKill].[vw_ContractLineSearch] AS cl
        JOIN (SELECT DISTINCT [vendor_part] FROM new_pbo) AS n ON n.[vendor_part] = cl.[vendor_item]
        WHERE cl.[vendor_name] LIKE '%MEDLINE%'
        GROUP BY cl.[vendor_item]
        HAVING COUNT(DISTINCT CONCAT(cl.[uom], '|', cl.[qoe])) = 1
    )
    INSERT INTO [FillKill].[Sub] (
        [medline_item], [vendor], [vendor_part], [description], [uom], [qoe],
        [status], [is_picked], [source], [entered_by], [create_dt], [update_dt]
    )
    OUTPUT inserted.[sub_id], inserted.[medline_item] INTO @added
    SELECT n.[medline_item], 'Medline', n.[vendor_part], c.[description], c.[uom],
           CASE WHEN c.[qoe] > 0 THEN c.[qoe] END,
           'pending_review', 0, 'medline_pbo', 'Medline', @now, @now
    FROM new_pbo AS n
    LEFT JOIN contract AS c ON c.[vendor_item] = n.[vendor_part];

    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [actor], [acted_at])
    SELECT 'sub', [sub_id], [medline_item], 'created', 'Medline', @now
    FROM @added;

    COMMIT TRANSACTION;

    SELECT COUNT(*) AS [added] FROM @added;
END;
GO

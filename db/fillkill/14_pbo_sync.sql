-- Medline PBO subs: FillKill.usp_SyncPboSubs adds a sub for every Medline PBO substitute of a
-- killed item that isn't a sub yet. Run on O2, database PLM, after 11, 12 and 13, BEFORE deploy #2
-- (plan v2 §4.3, P6). Safe to re-run.
--
-- The app calls it each time the main table loads. It is set-based and idempotent, and never
-- touches an existing sub. It skips a part the item already has as a sub (entered by nursing, or
-- deleted). A sub it adds (2026-10-20, after 12's step 2):
--   Reference SKU = the substitute number, status 'pending_review', source 'medline_pbo', entered
--   by 'Medline';
--   and a vendor item, when Medline's contract lines for that part (vendor ID 1000931,
--   @medline_vendor) agree on one UOM and QOE: Medline's name in Infor and its vendor ID, the
--   substitute number as the vendor part, and the lines' UOM, QOE, description, manufacturer's part
--   and Infor item number (item-master lines only). Otherwise the Materials Manager adds one.
-- Each gets a 'created' History row. Returns the number of subs added.

SET NOCOUNT ON;
GO

CREATE OR ALTER PROCEDURE [FillKill].[usp_SyncPboSubs]
AS
BEGIN
    -- version 2026-10-20: app/fillkill/health.py and 09_verify.sql look for this line; change them together.
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @now DATETIME = GETDATE();
    DECLARE @added TABLE ([sub_id] INT, [medline_item] VARCHAR(50), [reference_sku] VARCHAR(100));
    DECLARE @items TABLE ([vendor_item_id] INT, [sub_id] INT);
    -- MEDLINE INDUSTRIES INC; the same in 12 (which gave the older PBO subs this ID).
    DECLARE @medline_vendor VARCHAR(20) = '1000931';
    DECLARE @medline_name VARCHAR(255) = COALESCE(
        (SELECT TOP (1) [vendor_name] FROM [FillKill].[vw_Vendor] WHERE [vendor_id] = @medline_vendor),
        'MEDLINE INDUSTRIES INC');

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
        SELECT DISTINCT [Medline Item] AS [medline_item], [Medline.Sub] AS [reference_sku]
        FROM [FillKill].[vw_MedlineFillKillItemCollection]
        WHERE NULLIF(LTRIM([Medline.Sub]), '') IS NOT NULL
    )
    INSERT INTO [FillKill].[Sub] (
        [medline_item], [reference_sku], [status], [is_picked], [source], [entered_by], [create_dt], [update_dt]
    )
    OUTPUT inserted.[sub_id], inserted.[medline_item], inserted.[reference_sku] INTO @added
    SELECT p.[medline_item], p.[reference_sku], 'pending_review', 0, 'medline_pbo', 'Medline', @now, @now
    FROM pbo AS p
    WHERE NOT EXISTS (
        SELECT 1 FROM [FillKill].[Sub] AS s
        WHERE s.[medline_item] = p.[medline_item] AND s.[reference_sku] = p.[reference_sku]
        -- deleted ones too: nursing may have entered the part already, and a deleted PBO sub
        -- stays deleted
    );

    WITH contract AS (
        SELECT cl.[vendor_item], MAX(cl.[description]) AS [description],
               MAX(cl.[uom]) AS [uom], MAX(cl.[qoe]) AS [qoe],
               MAX(cl.[manufacturer_number]) AS [manufacturer_part],
               MAX(CASE WHEN cl.[item_type] = 'Itemmast' THEN cl.[infor_item] END) AS [infor_item]
        FROM [FillKill].[vw_ContractLineSearch] AS cl
        JOIN (SELECT DISTINCT [reference_sku] FROM @added) AS a ON a.[reference_sku] = cl.[vendor_item]
        WHERE cl.[vendor_id] = @medline_vendor
        GROUP BY cl.[vendor_item]
        HAVING COUNT(DISTINCT CONCAT(cl.[uom], '|', cl.[qoe])) = 1
    )
    INSERT INTO [FillKill].[SubVendorItem] (
        [sub_id], [vendor_part], [vendor], [vendor_id], [uom], [qoe], [manufacturer_part], [infor_item],
        [description], [entered_by], [create_dt], [update_dt]
    )
    OUTPUT inserted.[vendor_item_id], inserted.[sub_id] INTO @items
    SELECT a.[sub_id], a.[reference_sku], @medline_name, @medline_vendor, c.[uom],
           CASE WHEN c.[qoe] > 0 THEN c.[qoe] END, c.[manufacturer_part], c.[infor_item], c.[description],
           'Medline', @now, @now
    FROM @added AS a
    JOIN contract AS c ON c.[vendor_item] = a.[reference_sku]
    WHERE NULLIF(c.[uom], '') IS NOT NULL;

    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [actor], [acted_at])
    SELECT 'sub', [sub_id], [medline_item], 'created', 'Medline', @now
    FROM @added
    UNION ALL
    SELECT 'vendoritem', i.[vendor_item_id], a.[medline_item], 'created', 'Medline', @now
    FROM @items AS i JOIN @added AS a ON a.[sub_id] = i.[sub_id];

    COMMIT TRANSACTION;

    SELECT COUNT(*) AS [added] FROM @added;
END;
GO

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the tables it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those tables. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO

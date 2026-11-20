-- Medline's subs: FillKill.usp_SyncPboSubs adds a sub for every substitute Medline lists for a killed
-- item that isn't a sub yet. Run on O2, database PLM, after 11, 12 and 13. Safe to re-run.
--
-- Where Medline lists subs (11's vw_MedlineSubList, through the item view's Medline.Sub), each with a
-- rank, lower being more trusted. The rank says how the sync treats the sub (2026-11-19, the user):
--   rank  source             Medline's list                                    the sync adds it as
--   0     medline_autosub    Medline's AutoSub list                            approved
--   1     medline_preferred  the Fill/Kill file's Customer Preferred Substitute approved
--   2     medline_possible   the Fill/Kill file's Possible Subst. Item         pending review
--   3     medline_pbo        the PBO sub collection                            pending review
-- A sub on several lists takes its best rank. Approved subs can be ordered at once, as when nursing
-- enters one; nursing can still put one on Hold or reject it. A rank not in this table is left out:
-- if 11's ranks change, change this with them (and app/models/fillkill.py's SUB_SOURCES and
-- app/fillkill/rules.py's SOURCE_LABELS for a new source; 12's CK_Sub_source too).
--
-- The app calls it each time the main table loads. It is set-based and idempotent. A sub it adds:
--   Reference SKU = the substitute number, status and source as above, entered by 'Medline';
--   and a vendor item, when Medline's contract lines for that part (vendor ID 1000931,
--   @medline_vendor) agree on one UOM and QOE: Medline's name in Infor and its vendor ID, the
--   substitute number as the vendor part, and the lines' UOM, QOE, description, manufacturer's part
--   and Infor item number (item-master lines only). Otherwise the Materials Manager adds one.
-- It skips a part the item already has as a sub (entered by nursing, or deleted: a deleted sub stays
-- deleted). It changes only Medline's own subs still pending review (nobody has reviewed them): when
-- a more trusted list now has one, it takes that source, and is approved for rank 0 or 1. So a
-- Possible Sub Medline later puts on its AutoSub list is approved. Subs nursing has reviewed, and
-- subs anyone entered by hand, it never changes.
-- History: 'created' by Medline for each sub and vendor item it adds; by 'System', 'edit' (field
-- source, its labels) for each sub it relabels, and for each it approves 'status' (pending review to
-- approved) and a comment saying why, "Auto-approved: from Medline AutoSub" (or "... from Medline
-- FillKill Customer Preferred"), which Main shows under the sub as it shows nursing's.
-- Returns the number of subs added.
--
-- 2026-11-19: until then every sub it added was 'medline_pbo' and pending review (the 2026-10-20
-- version), whichever list it came from. Its first run relabels and approves those still pending.
-- 2026-11-19.2 (the user): the approval comment. The 2026-11-19 version approved without one; the
-- end of this script gives those subs theirs.

SET NOCOUNT ON;
GO

CREATE OR ALTER PROCEDURE [FillKill].[usp_SyncPboSubs]
AS
BEGIN
    -- version 2026-11-19.2 (after version 2026-11-19, and version 2026-10-20 before it):
    -- app/fillkill/health.py and 09_verify.sql look for "version 2026-11-19.2"; change them together.
    -- The release before it looks for the 2026-10-20 one.
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @now DATETIME = GETDATE();
    DECLARE @system VARCHAR(255) = 'System';  -- app/models/fillkill.py SYSTEM_ACTOR
    -- Each rank's source, its label (app/fillkill/rules.py SOURCE_LABELS) and the status it's added with.
    DECLARE @sources TABLE ([sub_rank] INT PRIMARY KEY, [source] VARCHAR(20), [label] VARCHAR(60), [status] VARCHAR(20));
    INSERT INTO @sources VALUES
        (0, 'medline_autosub', 'Medline AutoSub', 'approved'),
        (1, 'medline_preferred', 'Medline FillKill Customer Preferred', 'approved'),
        (2, 'medline_possible', 'Medline FillKill Possible Sub', 'pending_review'),
        (3, 'medline_pbo', 'Medline PBO', 'pending_review');
    DECLARE @offered TABLE ([medline_item] VARCHAR(50), [reference_sku] VARCHAR(100), [sub_rank] INT);
    DECLARE @added TABLE ([sub_id] INT, [medline_item] VARCHAR(50), [reference_sku] VARCHAR(100), [status] VARCHAR(20),
                          [source] VARCHAR(20));
    DECLARE @relabelled TABLE ([sub_id] INT, [medline_item] VARCHAR(50), [from_source] VARCHAR(20),
                               [to_source] VARCHAR(20), [status] VARCHAR(20));
    DECLARE @approved TABLE ([sub_id] INT, [medline_item] VARCHAR(50), [source] VARCHAR(20));
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

    -- Each killed item's subs, with their best rank over the item's UOMs.
    INSERT INTO @offered ([medline_item], [reference_sku], [sub_rank])
    SELECT [Medline Item], [Medline.Sub], MIN([Medline.SubRank])
    FROM [FillKill].[vw_MedlineFillKillItemCollection]
    WHERE NULLIF(LTRIM([Medline.Sub]), '') IS NOT NULL
    GROUP BY [Medline Item], [Medline.Sub];

    INSERT INTO [FillKill].[Sub] (
        [medline_item], [reference_sku], [status], [is_picked], [source], [entered_by], [create_dt], [update_dt]
    )
    OUTPUT inserted.[sub_id], inserted.[medline_item], inserted.[reference_sku], inserted.[status], inserted.[source]
        INTO @added
    SELECT o.[medline_item], o.[reference_sku], r.[status], 0, r.[source], 'Medline', @now, @now
    FROM @offered AS o
    JOIN @sources AS r ON r.[sub_rank] = o.[sub_rank]
    WHERE NOT EXISTS (
        SELECT 1 FROM [FillKill].[Sub] AS s
        WHERE s.[medline_item] = o.[medline_item] AND s.[reference_sku] = o.[reference_sku]
        -- deleted ones too: nursing may have entered the part already, and a deleted sub
        -- stays deleted
    );

    -- Medline's subs nobody has reviewed yet, now on a more trusted list.
    UPDATE s
    SET s.[source] = r.[source], s.[status] = r.[status], s.[update_dt] = @now
    OUTPUT inserted.[sub_id], inserted.[medline_item], deleted.[source], inserted.[source], inserted.[status]
        INTO @relabelled
    FROM [FillKill].[Sub] AS s
    JOIN @sources AS was ON was.[source] = s.[source]
    JOIN @offered AS o ON o.[medline_item] = s.[medline_item] AND o.[reference_sku] = s.[reference_sku]
    JOIN @sources AS r ON r.[sub_rank] = o.[sub_rank]
    WHERE s.[deleted_at] IS NULL AND s.[status] = 'pending_review' AND r.[sub_rank] < was.[sub_rank];

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

    -- One statement each, so a sub's rows are numbered in the order they happened.
    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [actor], [acted_at])
    SELECT 'sub', [sub_id], [medline_item], 'created', 'Medline', @now
    FROM @added;

    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [field], [from_value],
                                      [to_value], [actor], [acted_at])
    SELECT 'sub', x.[sub_id], x.[medline_item], 'edit', 'source', f.[label], t.[label], @system, @now
    FROM @relabelled AS x
    JOIN @sources AS f ON f.[source] = x.[from_source]
    JOIN @sources AS t ON t.[source] = x.[to_source];

    -- The subs it approved, added or relabelled, each with the list that approved it.
    INSERT INTO @approved ([sub_id], [medline_item], [source])
    SELECT [sub_id], [medline_item], [source] FROM @added WHERE [status] = 'approved'
    UNION ALL
    SELECT [sub_id], [medline_item], [to_source] FROM @relabelled WHERE [status] = 'approved';

    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [field], [from_value],
                                      [to_value], [actor], [acted_at])
    SELECT 'sub', [sub_id], [medline_item], 'status', 'status', 'pending_review', 'approved', @system, @now
    FROM @approved;

    -- Why, where nursing's comments go.
    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
    SELECT 'sub', a.[sub_id], a.[medline_item], 'comment', CONCAT('Auto-approved: from ', r.[label]), @system, @now
    FROM @approved AS a
    JOIN @sources AS r ON r.[source] = a.[source];

    INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [actor], [acted_at])
    SELECT 'vendoritem', i.[vendor_item_id], a.[medline_item], 'created', 'Medline', @now
    FROM @items AS i JOIN @added AS a ON a.[sub_id] = i.[sub_id];

    COMMIT TRANSACTION;

    SELECT COUNT(*) AS [added] FROM @added;
END;
GO

-- Once (2026-11-19.2): the subs the 2026-11-19 version approved got no comment. Each gets its own,
-- dated with its approval so a later comment of nursing's stays the latest. Labels as in @sources
-- above. Safe to re-run: a sub with a comment by System is left alone.
INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
SELECT 'sub', s.[sub_id], s.[medline_item], 'comment',
       CONCAT('Auto-approved: from ', CASE s.[source] WHEN 'medline_autosub' THEN 'Medline AutoSub'
                                                      ELSE 'Medline FillKill Customer Preferred' END),
       'System', a.[acted_at]
FROM [FillKill].[Sub] AS s
CROSS APPLY (SELECT MIN(h.[acted_at]) AS [acted_at] FROM [FillKill].[History] AS h
             WHERE h.[entity] = 'sub' AND h.[entity_id] = s.[sub_id] AND h.[action] = 'status'
               AND h.[to_value] = 'approved' AND h.[actor] = 'System') AS a
WHERE s.[source] IN ('medline_autosub', 'medline_preferred') AND a.[acted_at] IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS c
                  WHERE c.[entity] = 'sub' AND c.[entity_id] = s.[sub_id] AND c.[action] = 'comment'
                    AND c.[actor] = 'System');
PRINT CONCAT(@@ROWCOUNT, ' sub(s) the system approved got their comment');
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

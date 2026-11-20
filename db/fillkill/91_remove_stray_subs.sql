-- Removes the subs Medline added for an item that has no kill line at all: leftovers from before
-- real data (2026-11-20, the user). Run on O2, database PLM. As it is, it only lists them; to
-- delete them, change @confirm below to 'DELETE'. Safe to re-run.
--
-- On O2 on 11/20 there were four, all Medline PBO and pending review, which the Subs page lists
-- ("Never" on Fill/Kill) but Main can't open:
--   sub 1  BRD0102SI14H  DYND11591  (2026-11-02, with Medline's vendor item 1)
--   sub 2  MMM15382HH    NON270102  (2026-11-02)
--   sub 3  MMO2329H      2329RH     (2026-11-02)
--   sub 4  MMO2329H      2329R      (2026-11-13)
-- usp_SyncPboSubs (14) added them from the kill lines there were then: the test lines and Medline's
-- earlier file. On 11/16 those went (TestFillKillLine emptied, Medline's table holds its final
-- file's lines from 11/16 on) and the subs stayed. New ones like them can't appear by themselves:
-- the sync adds subs only for items with kill lines, and Medline's table never deletes a line.
--
-- Deleted here, not with the app's soft delete: the sync skips a part the item already has as a
-- sub, deleted ones too. Soft-deleted, such a sub would stay deleted if Medline killed the item
-- again; deleted here, the sync adds it fresh from Medline's list then.
--
-- Only a sub nobody has touched: entered by Medline, still pending review, not deleted, never
-- ordered, and nothing in History on it or its vendor items but Medline's 'created' (no comment,
-- edit or status change; no vendor item SCM added). It deletes those subs' History rows, their
-- vendor items and the subs. SCM's instructions (ItemInstruction) are the item's and stay.

SET NOCOUNT ON;

DECLARE @confirm VARCHAR(10) = 'no';

DECLARE @stray TABLE ([sub_id] INT PRIMARY KEY);
INSERT INTO @stray ([sub_id])
SELECT s.[sub_id]
FROM [FillKill].[Sub] AS s
WHERE s.[entered_by] = 'Medline' AND s.[status] = 'pending_review' AND s.[deleted_at] IS NULL
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[vw_MedlineFillKill] AS k WHERE k.[Item] = s.[medline_item])
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[SubOrder] AS o
                  WHERE o.[sub_id] = s.[sub_id]
                     OR o.[vendor_item_id] IN (SELECT v.[vendor_item_id] FROM [FillKill].[SubVendorItem] AS v
                                               WHERE v.[sub_id] = s.[sub_id]))
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                  WHERE ((h.[entity] = 'sub' AND h.[entity_id] = s.[sub_id])
                         OR (h.[entity] = 'vendoritem'
                             AND h.[entity_id] IN (SELECT v.[vendor_item_id] FROM [FillKill].[SubVendorItem] AS v
                                                   WHERE v.[sub_id] = s.[sub_id])))
                    AND NOT (h.[action] = 'created' AND h.[actor] = 'Medline'));

SELECT s.[sub_id], s.[medline_item] AS [Medline item], s.[reference_sku] AS [Reference SKU],
       s.[source], s.[create_dt] AS [added],
       (SELECT COUNT(*) FROM [FillKill].[SubVendorItem] AS v WHERE v.[sub_id] = s.[sub_id]) AS [vendor items]
FROM [FillKill].[Sub] AS s
JOIN @stray AS x ON x.[sub_id] = s.[sub_id]
ORDER BY s.[sub_id];

DECLARE @found INT = (SELECT COUNT(*) FROM @stray);
IF @confirm <> 'DELETE' OR @found = 0
BEGIN
    IF @found = 0
        PRINT 'No stray subs: nothing to delete.';
    ELSE
        PRINT CONCAT('Nothing deleted. The ', @found, ' sub(s) listed would go: set @confirm to ''DELETE'' to delete them.');
    RETURN;
END;

SET XACT_ABORT ON;  -- an error rolls the transaction back instead of leaving it open

BEGIN TRANSACTION;
DELETE h
FROM [FillKill].[History] AS h
WHERE (h.[entity] = 'sub' AND h.[entity_id] IN (SELECT [sub_id] FROM @stray))
   OR (h.[entity] = 'vendoritem'
       AND h.[entity_id] IN (SELECT v.[vendor_item_id] FROM [FillKill].[SubVendorItem] AS v
                             JOIN @stray AS x ON x.[sub_id] = v.[sub_id]));
PRINT CONCAT('History rows deleted: ', @@ROWCOUNT);
DELETE v
FROM [FillKill].[SubVendorItem] AS v
JOIN @stray AS x ON x.[sub_id] = v.[sub_id];
PRINT CONCAT('Vendor items deleted: ', @@ROWCOUNT);
DELETE s
FROM [FillKill].[Sub] AS s
JOIN @stray AS x ON x.[sub_id] = s.[sub_id];
PRINT CONCAT('Subs deleted: ', @@ROWCOUNT);
COMMIT TRANSACTION;
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

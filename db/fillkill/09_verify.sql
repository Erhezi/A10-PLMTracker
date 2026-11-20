-- Checks for the app's access tables and the Fill/Kill database objects.
-- Read-only; run after every script run. Every row should say PASS, except
-- 'users.user_role is admin or user', which says PENDING until 04 runs after the deploy, and
-- 'test lines gone', PENDING until 10 runs after the 2026-11-16 deploy. The
-- later result sets say FAIL until their scripts have run: kill lines (10, 11) and the
-- workflow (12-14); each check names its script.
--
-- The Fill/Kill checks are the ones the app makes on its Main page for admins and in
-- `flask fillkill check-db` (app/fillkill/health.py): change them together. This script can't
-- check the app's own account (its read grants, EXECUTE on usp_SyncPboSubs); check-db can.

SET NOCOUNT ON;

-- Deploy #1 -------------------------------------------------------------------

WITH admins AS (
    -- Admin is the app-level role in users.user_role.
    SELECT [user_id] FROM [PLM].[users] WHERE [user_role] = 'admin'
)
SELECT 'schema FillKill exists' AS [check],
       CASE WHEN SCHEMA_ID(N'FillKill') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
SELECT 'table PLM.UserModuleRole exists',
       CASE WHEN OBJECT_ID(N'[PLM].[UserModuleRole]', N'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- Checked by what the key does, whatever it is called.
SELECT 'deleting a user deletes their UserModuleRole rows',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.foreign_keys
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND referenced_object_id = OBJECT_ID(N'[PLM].[users]')
             AND delete_referential_action_desc = N'CASCADE'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'UserModuleRole accepts only known roles for plm and fillkill, SCM as scm (02, 2026-11-02)',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND definition LIKE '%editor%' AND definition LIKE '%sub[_]approver%'
             AND definition LIKE '%materials[_]manager%' AND definition LIKE '%''scm''%'
             AND definition NOT LIKE '%mm[_]lead%'
             AND definition NOT LIKE '%''app''%'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'a user holds at most one PLM role',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.indexes
           WHERE object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND name = N'UX_UserModuleRole_one_plm_role' AND is_unique = 1
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- Not system-generated names: if this fails, the app created the table before
-- 02_user_module_role.sql ran; re-running 02 renames them.
SELECT 'UserModuleRole constraints have their standard names',
       CASE WHEN (
           SELECT COUNT(*) FROM sys.objects
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND name IN (N'PK_UserModuleRole', N'FK_UserModuleRole_users',
                          N'CK_UserModuleRole_role', N'DF_UserModuleRole_granted_at')
       ) = 4 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'users.requested_modules exists',
       CASE WHEN COL_LENGTH(N'PLM.users', N'requested_modules') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'admin lives in users.user_role, not in UserModuleRole',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[UserModuleRole] WHERE [module] = 'app'
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- 'view-only' stays until 04_after_deploy.sql runs, after the new release is live.
SELECT 'users.user_role is admin or user',
       CASE
           WHEN NOT EXISTS (SELECT 1 FROM [PLM].[users] WHERE [user_role] NOT IN ('admin', 'user'))
               THEN 'PASS'
           WHEN NOT EXISTS (SELECT 1 FROM [PLM].[users] WHERE [user_role] NOT IN ('admin', 'user', 'view-only'))
               THEN 'PENDING: run 04 after the deploy'
           ELSE 'FAIL'
       END
UNION ALL
SELECT 'Fill/Kill Viewer is never combined with another Fill/Kill role',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[UserModuleRole] AS v
           WHERE v.[module] = 'fillkill' AND v.[role] = 'viewer'
             AND EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS o
                         WHERE o.[user_id] = v.[user_id] AND o.[module] = 'fillkill' AND o.[role] <> 'viewer')
       ) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'no non-admin holds both Sub Approver and Materials Manager',
       CASE WHEN NOT EXISTS (
           SELECT 1 FROM [PLM].[UserModuleRole] AS r
           WHERE r.[module] = 'fillkill' AND r.[role] IN ('sub_approver', 'materials_manager')
             AND r.[user_id] NOT IN (SELECT [user_id] FROM admins)
           GROUP BY r.[user_id]
           HAVING COUNT(DISTINCT r.[role]) = 2
       ) THEN 'PASS' ELSE 'FAIL' END;

-- Who holds what, for a quick eyeball.
SELECT u.[email],
       CASE WHEN u.[is_active] = 1 THEN 'active' ELSE 'pending/disabled' END AS [account],
       u.[user_role] AS [app_role],
       MAX(CASE WHEN r.[module] = 'plm' THEN r.[role] ELSE '' END) AS [plm],
       STRING_AGG(CASE WHEN r.[module] = 'fillkill' THEN r.[role] END, ', ')
           WITHIN GROUP (ORDER BY r.[role]) AS [fillkill]
FROM [PLM].[users] AS u
LEFT JOIN [PLM].[UserModuleRole] AS r ON r.[user_id] = u.[user_id]
GROUP BY u.[email], u.[is_active], u.[user_role]
ORDER BY u.[email];

-- Kill lines (10, 11) ------------------------------------------------------------

SELECT 'view FillKill.vw_MedlineFillKill exists (10)' AS [check],
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_MedlineFillKill]', N'V') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
SELECT 'vw_MedlineFillKill has Reason (Medline''s reason type), Reason Date, Ship-To Code (10, 2026-11-16)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Reason') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Reason Date') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Ship-To Code') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'ReasonTypeText') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'vw_MedlineFillKill has InforUOM, Medline''s UM as Infor calls it (10, 2026-11-18; 11 reads it)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'InforUOM') IS NOT NULL THEN 'PASS' ELSE 'FAIL: run 10' END
UNION ALL
SELECT 'view FillKill.vw_FillKillLastLoad exists (10)',
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_FillKillLastLoad]', N'V') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'vw_MedlineFillKillItemCollection has Infor Item, its consistency and Item.UOMConversion (11)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'Infor Item') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'Infor Item Consistency') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'Item.UOMConversion') IS NOT NULL
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'view FillKill.vw_MedlineSubList, Medline''s subs the item view reads (11, 2026-11-18)',
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_MedlineSubList]', N'V') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'InforUOM') IS NOT NULL
            THEN 'PASS' ELSE 'FAIL: run 11' END
UNION ALL
-- 14's procedure reads the rank, so 11 runs before 14.
SELECT 'vw_MedlineFillKillItemCollection has each sub''s best rank and source: Medline.SubRank, Medline.SubDataSource (11, 2026-11-19)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'Medline.SubRank') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKillItemCollection', N'Medline.SubDataSource') IS NOT NULL
            THEN 'PASS' ELSE 'FAIL: run 11' END
UNION ALL
-- They must read kill lines through vw_MedlineFillKill, not Medline's table directly.
SELECT 'item and quantity views read FillKill.vw_MedlineFillKill',
       CASE WHEN (
           SELECT COUNT(*) FROM sys.sql_modules
           WHERE object_id IN (OBJECT_ID(N'[FillKill].[vw_MedlineFillKillItemCollection]'),
                               OBJECT_ID(N'[FillKill].[vw_MedlineFillKillQtyAgg]'))
             AND CHARINDEX('vw_MedlineFillKill]', definition) > 0
             AND CHARINDEX('MedlineFillKill].[MedlineFillKill]', definition) = 0
             AND CHARINDEX('MedlineFillKill.MedlineFillKill', definition) = 0
       ) = 2 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- The test lines are gone (2026-11-16): 10, run after that day's deploy, drops their table and
-- the view's Is Test and Test Purpose (the release before reads Is Test).
SELECT 'test lines gone: no FillKill.TestFillKillLine, and no Is Test or Test Purpose in vw_MedlineFillKill (10, after the 2026-11-16 deploy)',
       CASE WHEN OBJECT_ID(N'[FillKill].[TestFillKillLine]', N'U') IS NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Is Test') IS NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Test Purpose') IS NULL THEN 'PASS'
            ELSE 'PENDING: run 10 after the deploy' END;

-- Kill-line reasons: Medline's reason type on every line (2026-11-16). Lists the reason types,
-- and the comments on lines Medline sent without one.
IF COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Ship-To Code') IS NOT NULL
    EXEC (N'
        SELECT ''kill lines have Medline''''s reason type'' AS [check],
               CASE WHEN NOT EXISTS (SELECT 1 FROM [FillKill].[vw_MedlineFillKill] WHERE [Reason] IS NULL)
                    THEN ''PASS'' ELSE ''CHECK: see the comments without a reason type below'' END AS [result];
        SELECT [Reason], COUNT(*) AS [lines], COUNT([Reason Date]) AS [with_date],
               COUNT([Ship-To Code]) AS [with_ship_to_code]
        FROM [FillKill].[vw_MedlineFillKill] GROUP BY [Reason] ORDER BY [lines] DESC;
        SELECT DISTINCT [Internal Order Comments from SAP (Z106)] AS [comment without a reason type]
        FROM [FillKill].[vw_MedlineFillKill] WHERE [Reason] IS NULL;
    ');

-- Workflow (12-14) ----------------------------------------------------------------

SELECT 'tables FillKill.Sub, SubVendorItem, SubOrder, History, ItemInstruction exist (12)' AS [check],
       CASE WHEN OBJECT_ID(N'[FillKill].[Sub]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[SubVendorItem]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[SubOrder]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[History]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[ItemInstruction]', N'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
-- A sub keeps what was entered; its vendor items keep the vendor details (12's step 2).
SELECT 'Sub has reference_sku, deleted_at, deleted_by, delete_reason, and no vendor details (12, 2026-10-20)',
       CASE WHEN COL_LENGTH(N'FillKill.Sub', N'reference_sku') IS NOT NULL
             AND COL_LENGTH(N'FillKill.Sub', N'deleted_at') IS NOT NULL
             AND COL_LENGTH(N'FillKill.Sub', N'deleted_by') IS NOT NULL
             AND COL_LENGTH(N'FillKill.Sub', N'delete_reason') IS NOT NULL
             AND COL_LENGTH(N'FillKill.Sub', N'vendor_part') IS NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'SubOrder has vendor_item_id, vendor_part, vendor_id (12, 2026-10-20)',
       CASE WHEN COL_LENGTH(N'FillKill.SubOrder', N'vendor_item_id') IS NOT NULL
             AND COL_LENGTH(N'FillKill.SubOrder', N'vendor_part') IS NOT NULL
             AND COL_LENGTH(N'FillKill.SubOrder', N'vendor_id') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'SubOrder has site and po_number (12, 2026-10-27)',
       CASE WHEN COL_LENGTH(N'FillKill.SubOrder', N'site') IS NOT NULL
             AND COL_LENGTH(N'FillKill.SubOrder', N'po_number') IS NOT NULL THEN 'PASS' ELSE 'FAIL: re-run 12' END
UNION ALL
SELECT 'one live sub per Medline item and Reference SKU: UX_Sub_item_reference_sku (12, 2026-10-20)',
       CASE WHEN (SELECT STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal)
                  FROM sys.indexes AS i
                  JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                  JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                  WHERE i.object_id = OBJECT_ID(N'[FillKill].[Sub]') AND i.name = N'UX_Sub_item_reference_sku'
                    AND i.is_unique = 1 AND i.has_filter = 1 AND ic.is_included_column = 0) = 'medline_item,reference_sku'
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'one live vendor item per sub, vendor ID, vendor part and UOM: UX_SubVendorItem_vendor_part_uom (12, 2026-10-20)',
       CASE WHEN (SELECT STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal)
                  FROM sys.indexes AS i
                  JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                  JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                  WHERE i.object_id = OBJECT_ID(N'[FillKill].[SubVendorItem]') AND i.name = N'UX_SubVendorItem_vendor_part_uom'
                    AND i.is_unique = 1 AND i.has_filter = 1 AND ic.is_included_column = 0) = 'sub_id,vendor_id,vendor_part,uom'
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
-- A vendor item without a sub is for a Medline item, as SCM directs (12's step 4).
SELECT 'vendor items without a sub (12, 2026-11-02): SubVendorItem.medline_item, sub_id may be empty on SubVendorItem and SubOrder, their index and checks',
       CASE WHEN COL_LENGTH(N'FillKill.SubVendorItem', N'medline_item') IS NOT NULL
             AND COLUMNPROPERTY(OBJECT_ID(N'[FillKill].[SubVendorItem]'), N'sub_id', 'AllowsNull') = 1
             AND COLUMNPROPERTY(OBJECT_ID(N'[FillKill].[SubOrder]'), N'sub_id', 'AllowsNull') = 1
             AND EXISTS (SELECT 1 FROM sys.indexes
                         WHERE object_id = OBJECT_ID(N'[FillKill].[SubVendorItem]') AND name = N'UX_SubVendorItem_vendor_part_uom'
                           AND filter_definition LIKE N'%sub_id%')
             AND (SELECT STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal)
                  FROM sys.indexes AS i
                  JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                  JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                  WHERE i.object_id = OBJECT_ID(N'[FillKill].[SubVendorItem]') AND i.name = N'UX_SubVendorItem_item_vendor_part_uom'
                    AND i.is_unique = 1 AND i.has_filter = 1 AND ic.is_included_column = 0) = 'medline_item,vendor_id,vendor_part,uom'
             AND OBJECT_ID(N'[FillKill].[CK_SubVendorItem_sub_or_item]', N'C') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[CK_SubOrder_sub_or_vendor_item]', N'C') IS NOT NULL
            THEN 'PASS' ELSE 'FAIL: re-run 12' END
UNION ALL
-- The names app/models/fillkill.py uses; if the app created a table first, its constraints match.
SELECT 'workflow constraints have their standard names (12)',
       CASE WHEN (
           SELECT COUNT(*) FROM sys.objects
           WHERE name IN (N'PK_Sub', N'CK_Sub_status', N'CK_Sub_source', N'CK_Sub_pick_needs_approved', N'CK_Sub_delete',
                          N'PK_SubVendorItem', N'FK_SubVendorItem_Sub', N'CK_SubVendorItem_qoe', N'CK_SubVendorItem_delete',
                          N'PK_SubOrder', N'FK_SubOrder_Sub', N'FK_SubOrder_SubVendorItem', N'CK_SubOrder_quantity',
                          N'CK_SubOrder_qoe', N'CK_SubOrder_void',
                          N'PK_History', N'CK_History_entity', N'CK_History_action',
                          N'PK_ItemInstruction',
                          N'DF_Sub_status', N'DF_Sub_is_picked', N'DF_Sub_create_dt', N'DF_Sub_update_dt',
                          N'DF_SubVendorItem_create_dt', N'DF_SubVendorItem_update_dt',
                          N'DF_SubOrder_create_dt', N'DF_SubOrder_update_dt', N'DF_History_acted_at',
                          N'DF_ItemInstruction_written_at')
             AND SCHEMA_NAME(schema_id) = N'FillKill'
       ) = 29 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'History can record vendor items and deletes: CK_History_entity and CK_History_action (12, 2026-10-20)',
       CASE WHEN EXISTS (SELECT 1 FROM sys.check_constraints
                         WHERE parent_object_id = OBJECT_ID(N'[FillKill].[History]') AND name = N'CK_History_action'
                           AND definition LIKE N'%''delete''%')
             AND EXISTS (SELECT 1 FROM sys.check_constraints
                         WHERE parent_object_id = OBJECT_ID(N'[FillKill].[History]') AND name = N'CK_History_entity'
                           AND definition LIKE N'%''vendoritem''%')
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'a sub says which of Medline''s lists it came from: CK_Sub_source (12, 2026-11-19)',
       CASE WHEN EXISTS (SELECT 1 FROM sys.check_constraints
                         WHERE parent_object_id = OBJECT_ID(N'[FillKill].[Sub]') AND name = N'CK_Sub_source'
                           AND definition LIKE N'%''medline[_]autosub''%' AND definition LIKE N'%''medline[_]preferred''%'
                           AND definition LIKE N'%''medline[_]possible''%' AND definition LIKE N'%''medline[_]pbo''%')
            THEN 'PASS' ELSE 'FAIL: re-run 12' END
UNION ALL
SELECT 'view FillKill.vw_ContractLineSearch has is_mhs (13)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_ContractLineSearch', N'is_mhs') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'view FillKill.vw_Vendor has the legal and search names (13, 2026-10-19)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_Vendor', N'legal_name') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_Vendor', N'search_name') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'view FillKill.vw_UomAlias, typed UOMs to Infor''s (13, 2026-10-20)',
       CASE WHEN COL_LENGTH(N'FillKill.vw_UomAlias', N'external_value') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_UomAlias', N'lawson_value') IS NOT NULL THEN 'PASS' ELSE 'FAIL: run 13' END
UNION ALL
-- The version line near the top of 14; change both together.
SELECT 'procedure FillKill.usp_SyncPboSubs is the 2026-11-19.2 version: each sub''s source, AutoSub and Customer Preferred approved with a comment saying so (14)',
       CASE WHEN OBJECT_ID(N'[FillKill].[usp_SyncPboSubs]', N'P') IS NULL THEN 'FAIL: run 14'
            WHEN OBJECT_DEFINITION(OBJECT_ID(N'[FillKill].[usp_SyncPboSubs]')) IS NULL
                THEN 'CHECK: no VIEW DEFINITION permission to read it'
            WHEN OBJECT_DEFINITION(OBJECT_ID(N'[FillKill].[usp_SyncPboSubs]')) LIKE N'%version 2026-11-19.2%' THEN 'PASS'
            ELSE 'FAIL: an older version; re-run 14 (after 11 and 12)' END
UNION ALL
-- 12's step 2 saves a copy of Sub before it drops the vendor details.
SELECT 'copy of Sub from before vendor items (12, 2026-10-20)',
       CASE WHEN OBJECT_ID(N'[FillKill].[Sub_before_vendor_items]', N'U') IS NULL THEN 'INFO: none'
            ELSE 'INFO: FillKill.Sub_before_vendor_items is there; drop it once the subs look right' END;

-- Workflow data, once the tables exist and 12 is current.
IF COL_LENGTH(N'FillKill.Sub', N'reference_sku') IS NOT NULL AND OBJECT_ID(N'[FillKill].[SubVendorItem]', N'U') IS NOT NULL
    EXEC (N'
        SELECT ''every order is for its sub''''s Medline item, and its vendor item is that sub''''s'' AS [check],
               CASE WHEN NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubOrder] AS o JOIN [FillKill].[Sub] AS s ON s.[sub_id] = o.[sub_id]
                   LEFT JOIN [FillKill].[SubVendorItem] AS v ON v.[vendor_item_id] = o.[vendor_item_id]
                   WHERE o.[medline_item] <> s.[medline_item] OR v.[sub_id] <> o.[sub_id]
               ) THEN ''PASS'' ELSE ''FAIL'' END AS [result]
        UNION ALL
        SELECT ''every sub, vendor item and order has a created History row'',
               CASE WHEN NOT EXISTS (
                   SELECT 1 FROM [FillKill].[Sub] AS s
                   WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                                     WHERE h.[entity] = ''sub'' AND h.[entity_id] = s.[sub_id] AND h.[action] = ''created'')
               ) AND NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubVendorItem] AS v
                   WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                                     WHERE h.[entity] = ''vendoritem'' AND h.[entity_id] = v.[vendor_item_id]
                                       AND h.[action] = ''created'')
               ) AND NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubOrder] AS o
                   WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                                     WHERE h.[entity] = ''order'' AND h.[entity_id] = o.[order_id] AND h.[action] = ''created'')
               ) THEN ''PASS'' ELSE ''FAIL'' END
        UNION ALL
        SELECT ''orders without a vendor item (recorded before vendor items, with details the sub no longer had)'',
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[SubOrder] WHERE [vendor_item_id] IS NULL))
        UNION ALL
        SELECT ''workflow rows (subs / vendor items / orders / history)'',
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[Sub]), '' / '',
                      (SELECT COUNT(*) FROM [FillKill].[SubVendorItem]), '' / '',
                      (SELECT COUNT(*) FROM [FillKill].[SubOrder]), '' / '',
                      (SELECT COUNT(*) FROM [FillKill].[History]));
    ');

-- Coordination (12, 2026-10-27), once its columns and table exist.
IF COL_LENGTH(N'FillKill.SubOrder', N'site') IS NOT NULL AND OBJECT_ID(N'[FillKill].[ItemInstruction]', N'U') IS NOT NULL
    EXEC (N'
        SELECT ''orders without a site (recorded before 2026-10-27)'' AS [check],
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[SubOrder] WHERE [site] IS NULL), '' of '',
                      (SELECT COUNT(*) FROM [FillKill].[SubOrder])) AS [result]
        UNION ALL
        SELECT ''SCM instructions'',
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[ItemInstruction]), '' on '',
                      (SELECT COUNT(DISTINCT COALESCE([infor_item], [medline_item])) FROM [FillKill].[ItemInstruction]),
                      '' item(s)'');
    ');

-- Vendor items without a sub (12, 2026-11-02), once its column exists.
IF COL_LENGTH(N'FillKill.SubVendorItem', N'medline_item') IS NOT NULL
    EXEC (N'
        SELECT ''every order without a sub is for a vendor item without one, of its Medline item'' AS [check],
               CASE WHEN NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubOrder] AS o
                   LEFT JOIN [FillKill].[SubVendorItem] AS v ON v.[vendor_item_id] = o.[vendor_item_id]
                   WHERE o.[sub_id] IS NULL
                     AND (v.[vendor_item_id] IS NULL OR v.[sub_id] IS NOT NULL OR v.[medline_item] <> o.[medline_item])
               ) THEN ''PASS'' ELSE ''FAIL'' END AS [result]
        UNION ALL
        SELECT ''vendor items without a sub (live), and orders of them'',
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[SubVendorItem] WHERE [sub_id] IS NULL AND [deleted_at] IS NULL),
                      '' / '', (SELECT COUNT(*) FROM [FillKill].[SubOrder] WHERE [sub_id] IS NULL));
    ');

-- Live subs by where they came from (14, 2026-11-19), for a look: once Main has loaded after 14,
-- Medline's AutoSub and Customer Preferred subs are approved unless nursing changed them, and no
-- Medline sub still pending review is on a more trusted list than its source says.
IF COL_LENGTH(N'FillKill.Sub', N'reference_sku') IS NOT NULL
BEGIN
    -- 14's script gives the subs the 2026-11-19 version approved their comment (2026-11-19.2).
    SELECT 'every sub the system approved has its comment saying why (14, 2026-11-19.2)' AS [check],
           CASE WHEN NOT EXISTS (
               SELECT 1 FROM [FillKill].[History] AS h
               WHERE h.[entity] = 'sub' AND h.[action] = 'status' AND h.[to_value] = 'approved' AND h.[actor] = 'System'
                 AND NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS c
                                 WHERE c.[entity] = 'sub' AND c.[entity_id] = h.[entity_id] AND c.[action] = 'comment'
                                   AND c.[actor] = 'System' AND c.[comment] LIKE 'Auto-approved: %')
           ) THEN 'PASS' ELSE 'FAIL: re-run 14' END AS [result];
    SELECT [source], [status], COUNT(*) AS [live subs]
    FROM [FillKill].[Sub] WHERE [deleted_at] IS NULL
    GROUP BY [source], [status] ORDER BY [source], [status];
END;

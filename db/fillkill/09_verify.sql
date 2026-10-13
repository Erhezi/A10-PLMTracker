-- Checks for the app's access tables and the Fill/Kill database objects.
-- Read-only; run after every script run. Every row should say PASS, except
-- 'users.user_role is admin or user', which says PENDING until 04 runs after the deploy. The
-- later result sets say FAIL until their scripts have run: kill lines (10, 11) and the
-- workflow (12-14).

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
SELECT 'UserModuleRole accepts only known roles for plm and fillkill',
       CASE WHEN EXISTS (
           SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = OBJECT_ID(N'[PLM].[UserModuleRole]')
             AND definition LIKE '%editor%' AND definition LIKE '%sub[_]approver%'
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

SELECT 'view FillKill.vw_MedlineFillKill exists' AS [check],
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_MedlineFillKill]', N'V') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
SELECT 'vw_MedlineFillKill has Reason and Reason Date',
       CASE WHEN COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Reason') IS NOT NULL
             AND COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Reason Date') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'view FillKill.vw_FillKillLastLoad exists',
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_FillKillLastLoad]', N'V') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
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
-- Not a pass/fail: test copies under 'test site'. Empty the table at go-live.
SELECT 'test lines in FillKill.TestFillKillLine (empty at go-live)',
       CONCAT('INFO: ', ISNULL((SELECT SUM(p.[rows]) FROM sys.partitions AS p
                                WHERE p.[object_id] = OBJECT_ID(N'[FillKill].[TestFillKillLine]')
                                  AND p.[index_id] IN (0, 1)), 0), ' line(s)');

-- Kill-line reasons: every comment should fall into a known category. Lists any that don't.
IF COL_LENGTH(N'FillKill.vw_MedlineFillKill', N'Reason') IS NOT NULL
    EXEC (N'
        SELECT ''kill-line comments have a known reason'' AS [check],
               CASE WHEN NOT EXISTS (SELECT 1 FROM [FillKill].[vw_MedlineFillKill] WHERE [Reason] = ''OTHER'')
                    THEN ''PASS'' ELSE ''CHECK: see the OTHER comments below'' END AS [result];
        SELECT [Reason], COUNT(*) AS [lines], COUNT([Reason Date]) AS [with_date]
        FROM [FillKill].[vw_MedlineFillKill] GROUP BY [Reason] ORDER BY [lines] DESC;
        SELECT DISTINCT [Internal Order Comments from SAP (Z106)] AS [OTHER comment]
        FROM [FillKill].[vw_MedlineFillKill] WHERE [Reason] = ''OTHER'';
    ');

-- Workflow (12-14) ----------------------------------------------------------------

SELECT 'tables FillKill.Sub, SubOrder, History exist' AS [check],
       CASE WHEN OBJECT_ID(N'[FillKill].[Sub]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[SubOrder]', N'U') IS NOT NULL
             AND OBJECT_ID(N'[FillKill].[History]', N'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS [result]
UNION ALL
-- The names app/models/fillkill.py uses; if the app created a table first, its constraints match.
SELECT 'workflow constraints have their standard names',
       CASE WHEN (
           SELECT COUNT(*) FROM sys.objects
           WHERE name IN (N'PK_Sub', N'UQ_Sub_item_vendor_part', N'CK_Sub_status', N'CK_Sub_source',
                          N'CK_Sub_pick_needs_approved', N'CK_Sub_qoe',
                          N'PK_SubOrder', N'FK_SubOrder_Sub', N'CK_SubOrder_quantity', N'CK_SubOrder_qoe',
                          N'CK_SubOrder_void',
                          N'PK_History', N'CK_History_entity', N'CK_History_action',
                          N'DF_Sub_status', N'DF_Sub_is_picked', N'DF_Sub_create_dt', N'DF_Sub_update_dt',
                          N'DF_SubOrder_create_dt', N'DF_SubOrder_update_dt', N'DF_History_acted_at')
             AND SCHEMA_NAME(schema_id) = N'FillKill'
       ) = 21 THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'view FillKill.vw_ContractLineSearch exists',
       CASE WHEN OBJECT_ID(N'[FillKill].[vw_ContractLineSearch]', N'V') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'procedure FillKill.usp_SyncPboSubs exists',
       CASE WHEN OBJECT_ID(N'[FillKill].[usp_SyncPboSubs]', N'P') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END;

-- Workflow data, once the tables exist.
IF OBJECT_ID(N'[FillKill].[History]', N'U') IS NOT NULL
    EXEC (N'
        SELECT ''every order is for its sub''''s Medline item'' AS [check],
               CASE WHEN NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubOrder] AS o JOIN [FillKill].[Sub] AS s ON s.[sub_id] = o.[sub_id]
                   WHERE o.[medline_item] <> s.[medline_item]
               ) THEN ''PASS'' ELSE ''FAIL'' END AS [result]
        UNION ALL
        SELECT ''every sub and order has a created History row'',
               CASE WHEN NOT EXISTS (
                   SELECT 1 FROM [FillKill].[Sub] AS s
                   WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                                     WHERE h.[entity] = ''sub'' AND h.[entity_id] = s.[sub_id] AND h.[action] = ''created'')
               ) AND NOT EXISTS (
                   SELECT 1 FROM [FillKill].[SubOrder] AS o
                   WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                                     WHERE h.[entity] = ''order'' AND h.[entity_id] = o.[order_id] AND h.[action] = ''created'')
               ) THEN ''PASS'' ELSE ''FAIL'' END
        UNION ALL
        SELECT ''workflow rows (subs / orders / history)'',
               CONCAT(''INFO: '', (SELECT COUNT(*) FROM [FillKill].[Sub]), '' / '',
                      (SELECT COUNT(*) FROM [FillKill].[SubOrder]), '' / '',
                      (SELECT COUNT(*) FROM [FillKill].[History]));
    ');

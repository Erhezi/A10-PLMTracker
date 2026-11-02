-- Roles inside each module: one row per (user, module, role). Plan §4.1, P1;
-- unified access 2026-10-12. Run on O2, database PLM, BEFORE deploy #1. Safe to re-run.
--
--   plm       viewer | editor                         at most one of the two
--   fillkill  viewer alone, or any of sub_finder, sub_approver, materials_manager, scm
--             (sub_approver + materials_manager together only for admins; the app checks
--             both rules, 09_verify.sql reports any breach). scm (SCM) since 2026-10-27, coded
--             mm_lead until 2026-11-02: this script renames those rows.
--
-- Admin is not a row here: it is the app-level role in users.user_role ('admin' or 'user'),
-- and grants nothing inside a module, so admins get no roles by default.
-- Then run 03_unify_roles.sql, which gives everyone the PLM role matching today's user_role.

SET NOCOUNT ON;

IF OBJECT_ID(N'[PLM].[UserModuleRole]', N'U') IS NULL
BEGIN
    CREATE TABLE [PLM].[UserModuleRole] (
        [user_id]    INT          NOT NULL,
        [module]     VARCHAR(30)  NOT NULL,
        [role]       VARCHAR(30)  NOT NULL,
        [granted_by] VARCHAR(255) NULL,
        [granted_at] DATETIME     NOT NULL
            CONSTRAINT [DF_UserModuleRole_granted_at] DEFAULT (GETDATE()),
        CONSTRAINT [PK_UserModuleRole] PRIMARY KEY CLUSTERED ([user_id], [module], [role]),
        CONSTRAINT [FK_UserModuleRole_users] FOREIGN KEY ([user_id])
            REFERENCES [PLM].[users] ([user_id]) ON DELETE CASCADE,
        CONSTRAINT [CK_UserModuleRole_role] CHECK (
               ([module] = 'plm'      AND [role] IN ('viewer', 'editor'))
            OR ([module] = 'fillkill' AND [role] IN ('viewer', 'sub_finder', 'sub_approver', 'materials_manager', 'scm'))
        )
    );
END;
GO

-- Repair: if the app's startup (db.create_all) created the table before this
-- script ran, its constraints have system-generated names and the CHECK and the
-- default may be missing. Bring it to the same shape as a fresh CREATE above.
DECLARE @table INT = OBJECT_ID(N'[PLM].[UserModuleRole]');
DECLARE @name SYSNAME, @object NVARCHAR(300), @sql NVARCHAR(MAX);

-- Primary key name.
SET @name = NULL;
SELECT @name = name FROM sys.key_constraints
WHERE parent_object_id = @table AND type = 'PK' AND name <> N'PK_UserModuleRole';
IF @name IS NOT NULL
BEGIN
    SET @object = N'PLM.' + QUOTENAME(@name);
    EXEC sp_rename @object, N'PK_UserModuleRole', N'OBJECT';
    PRINT CONCAT('Renamed primary key ', @name, ' -> PK_UserModuleRole');
END;

-- Foreign key to users: keep it if it cascades (just rename), otherwise replace it.
SET @name = NULL;
SELECT @name = name FROM sys.foreign_keys
WHERE parent_object_id = @table
  AND referenced_object_id = OBJECT_ID(N'[PLM].[users]')
  AND name <> N'FK_UserModuleRole_users';
IF @name IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM sys.foreign_keys
               WHERE parent_object_id = @table AND name = @name
                 AND delete_referential_action_desc = N'CASCADE')
    BEGIN
        SET @object = N'PLM.' + QUOTENAME(@name);
        EXEC sp_rename @object, N'FK_UserModuleRole_users', N'OBJECT';
        PRINT CONCAT('Renamed foreign key ', @name, ' -> FK_UserModuleRole_users');
    END
    ELSE
    BEGIN
        SET @sql = N'ALTER TABLE [PLM].[UserModuleRole] DROP CONSTRAINT ' + QUOTENAME(@name) + N';';
        EXEC sp_executesql @sql;
        PRINT CONCAT('Dropped non-cascading foreign key ', @name);
    END;
END;
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys
               WHERE parent_object_id = @table AND name = N'FK_UserModuleRole_users')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] ADD CONSTRAINT [FK_UserModuleRole_users]
        FOREIGN KEY ([user_id]) REFERENCES [PLM].[users] ([user_id]) ON DELETE CASCADE;
    PRINT 'Added FK_UserModuleRole_users';
END;

-- Admin used to be kept here as module 'app' (an earlier 03_unify_roles.sql wrote those
-- rows). It now lives in users.user_role, so move any such rows there before the CHECK.
IF EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] WHERE [module] = 'app')
BEGIN
    SET XACT_ABORT ON;  -- an error rolls the transaction back instead of leaving it open
    BEGIN TRANSACTION;
    UPDATE u SET u.[user_role] = 'admin'
    FROM [PLM].[users] AS u
    WHERE u.[user_role] <> 'admin'
      AND EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS r
                  WHERE r.[user_id] = u.[user_id] AND r.[module] = 'app' AND r.[role] = 'admin');
    PRINT CONCAT('Admins newly set in users.user_role: ', @@ROWCOUNT);
    DELETE FROM [PLM].[UserModuleRole] WHERE [module] = 'app';
    PRINT CONCAT('Removed app-level rows from UserModuleRole: ', @@ROWCOUNT);
    COMMIT TRANSACTION;
END;

-- Allowed roles per module. Replaces earlier versions: the Fill/Kill-only CHECK, one
-- that also allowed module 'app', ones with the old Fill/Kill role codes, and ones without
-- scm (SCM, 2026-10-27; coded mm_lead until 2026-11-02).
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_fillkill_role')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] DROP CONSTRAINT [CK_UserModuleRole_fillkill_role];
    PRINT 'Dropped CK_UserModuleRole_fillkill_role (replaced by CK_UserModuleRole_role)';
END;
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_role'
             AND (definition LIKE N'%''app''%' OR definition NOT LIKE N'%sub[_]finder%'
                  OR definition NOT LIKE N'%''scm''%'))
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] DROP CONSTRAINT [CK_UserModuleRole_role];
    PRINT 'Dropped an earlier CK_UserModuleRole_role';
END;

-- Fill/Kill roles renamed 2026-10-13 (they were A/B/C in the design discussions), and
-- mm_lead to scm on 2026-11-02 (the role shows as SCM; it was the MM Lead).
UPDATE r SET r.[role] = m.[new_role]
FROM [PLM].[UserModuleRole] AS r
JOIN (VALUES ('proposer', 'sub_finder'),
             ('clinical', 'sub_approver'),
             ('materials', 'materials_manager'),
             ('mm_lead', 'scm')) AS m ([old_role], [new_role])
  ON r.[role] = m.[old_role]
WHERE r.[module] = 'fillkill';
PRINT CONCAT('Fill/Kill roles renamed: ', @@ROWCOUNT);

-- Fill/Kill Viewer is held alone; every other Fill/Kill role can already view.
DELETE v FROM [PLM].[UserModuleRole] AS v
WHERE v.[module] = 'fillkill' AND v.[role] = 'viewer'
  AND EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS o
              WHERE o.[user_id] = v.[user_id] AND o.[module] = 'fillkill' AND o.[role] <> 'viewer');
PRINT CONCAT('Fill/Kill Viewer removed where another Fill/Kill role is held: ', @@ROWCOUNT);

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_role')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] ADD CONSTRAINT [CK_UserModuleRole_role] CHECK (
           ([module] = 'plm'      AND [role] IN ('viewer', 'editor'))
        OR ([module] = 'fillkill' AND [role] IN ('viewer', 'sub_finder', 'sub_approver', 'materials_manager', 'scm'))
    );
    PRINT 'Added CK_UserModuleRole_role';
END;

-- Default for granted_at: rename a system-named one, or add it.
SET @name = NULL;
SELECT @name = dc.name FROM sys.default_constraints AS dc
JOIN sys.columns AS c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
WHERE dc.parent_object_id = @table AND c.name = N'granted_at';
IF @name IS NULL
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] ADD CONSTRAINT [DF_UserModuleRole_granted_at]
        DEFAULT (GETDATE()) FOR [granted_at];
    PRINT 'Added DF_UserModuleRole_granted_at';
END
ELSE IF @name <> N'DF_UserModuleRole_granted_at'
BEGIN
    SET @object = N'PLM.' + QUOTENAME(@name);
    EXEC sp_rename @object, N'DF_UserModuleRole_granted_at', N'OBJECT';
    PRINT CONCAT('Renamed default ', @name, ' -> DF_UserModuleRole_granted_at');
END;

-- A user holds at most one PLM role (Viewer or Editor).
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = @table AND name = N'UX_UserModuleRole_one_plm_role')
BEGIN
    CREATE UNIQUE INDEX [UX_UserModuleRole_one_plm_role]
        ON [PLM].[UserModuleRole] ([user_id]) WHERE [module] = 'plm';
    PRINT 'Added UX_UserModuleRole_one_plm_role';
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

-- Roles inside each module: one row per (user, module, role). Plan §4.1, P1;
-- unified access 2026-10-12. Run on O2, database PLM, BEFORE deploy #1. Safe to re-run.
--
--   plm       viewer | editor                         at most one of the two
--   fillkill  viewer, proposer (A), clinical (B), materials (C)
--
-- Admin is not a row here: it is the app-level role in users.user_role ('admin' or 'user').
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
            OR ([module] = 'fillkill' AND [role] IN ('viewer', 'proposer', 'clinical', 'materials'))
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

-- Allowed roles per module. Replaces earlier versions: the Fill/Kill-only CHECK, and
-- one that also allowed module 'app'.
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_fillkill_role')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] DROP CONSTRAINT [CK_UserModuleRole_fillkill_role];
    PRINT 'Dropped CK_UserModuleRole_fillkill_role (replaced by CK_UserModuleRole_role)';
END;
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_role'
             AND definition LIKE N'%''app''%')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] DROP CONSTRAINT [CK_UserModuleRole_role];
    PRINT 'Dropped CK_UserModuleRole_role that allowed module app';
END;
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE parent_object_id = @table AND name = N'CK_UserModuleRole_role')
BEGIN
    ALTER TABLE [PLM].[UserModuleRole] ADD CONSTRAINT [CK_UserModuleRole_role] CHECK (
           ([module] = 'plm'      AND [role] IN ('viewer', 'editor'))
        OR ([module] = 'fillkill' AND [role] IN ('viewer', 'proposer', 'clinical', 'materials'))
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

-- Admins start with every Fill/Kill role (P1). Only admins with no Fill/Kill rows
-- at all are seeded, so re-running never undoes a role an admin switched off.
INSERT INTO [PLM].[UserModuleRole] ([user_id], [module], [role], [granted_by], [granted_at])
SELECT u.[user_id], 'fillkill', r.[role], 'seed: 02_user_module_role.sql', GETDATE()
FROM [PLM].[users] AS u
CROSS JOIN (VALUES ('viewer'), ('proposer'), ('clinical'), ('materials')) AS r ([role])
WHERE u.[user_role] = 'admin'
  AND NOT EXISTS (
      SELECT 1 FROM [PLM].[UserModuleRole] AS x
      WHERE x.[user_id] = u.[user_id] AND x.[module] = 'fillkill'
  );

PRINT CONCAT('Seeded Fill/Kill roles: ', @@ROWCOUNT, ' row(s).');
GO

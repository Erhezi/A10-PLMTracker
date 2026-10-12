-- Per-module roles for shared users (plan §4.1, P1).
-- Run on O2, database PLM, BEFORE deploy #1. Safe to re-run.
--
-- users.user_role keeps its PLM meaning; this table holds roles for other modules.
-- Fill/Kill roles: viewer, proposer (A - sub entry), clinical (B - nursing),
-- materials (C - materials manager).

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
        CONSTRAINT [CK_UserModuleRole_fillkill_role] CHECK (
            [module] <> 'fillkill'
            OR [role] IN ('viewer', 'proposer', 'clinical', 'materials')
        )
    );
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

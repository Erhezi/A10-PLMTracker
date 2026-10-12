-- Only if deploy #1 has to be rolled back. Run on O2, database PLM, just BEFORE the
-- previous release goes back on the server. Safe to re-run.
--
-- The previous release reads only users.user_role: 'admin', 'user' (PLM editor) or
-- 'view-only' (PLM read-only). This sets it from each person's PLM role, so everyone
-- keeps the PLM access they have now; a non-admin without PLM Editor becomes
-- 'view-only', the least the previous release can give.
--
-- The new release reads 'view-only' as 'user', so running this early does no harm.
-- Leave the new table and column in place: redeploying deploy #1 picks them up again.

SET NOCOUNT ON;

UPDATE u
SET u.[user_role] =
        CASE WHEN EXISTS (SELECT 1 FROM [PLM].[UserModuleRole] AS r
                          WHERE r.[user_id] = u.[user_id] AND r.[module] = 'plm' AND r.[role] = 'editor')
             THEN 'user' ELSE 'view-only' END
FROM [PLM].[users] AS u
WHERE u.[user_role] <> 'admin';

PRINT CONCAT('Non-admin accounts set for the previous release: ', @@ROWCOUNT);
GO

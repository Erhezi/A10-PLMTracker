-- PLM.usp_RunPLM_ItemGroup recomputes one item group's rolling burn rates, the last two steps of
-- the morning batch (usp_RunPLM_Batch) narrowed to that group: PLMItemGroupBRRolling for each group
-- location, then PLMItemBRRolling for each link at each location of its items. Use it after a
-- group's links change between batches: a link added, deleted, or given a different item
-- (2026-10-22: group 5's replacement corrected from 106592 to 112055). Run on O2, database PLM.
-- Safe to re-run.
--
--     EXEC PLM.usp_RunPLM_ItemGroup @ItemGroup = 5;
--
-- Only those two tables depend on which items a group holds. The batch's first steps
-- (ItemLocations, ItemStartEndDate, DailyIssueOutQty, ItemLocationsBR) cover every item at every
-- I%/P% location in company 3000, tracked or not, so an item stocked when the batch ran is already
-- there. An item new to Infor since then gets its locations from the next batch.
--
-- Before recomputing, it deletes the group's rows the batch never refreshes again, and so never
-- deletes: a location the group no longer has, an item or link that left the group, and rows under
-- an Inventory_base_ID from an older ItemLocations (IDs are renumbered each batch, and
-- sp_PLM_PersistItemBRRolling deletes by item and location, so a new ID could collide with one).
--
-- Each call is logged in PLMItemGroupBRRolling_Log / PLMItemBRRolling_Log as the batch logs it,
-- but nothing goes in process_log: vw_PLMZDate takes its latest end time as when the base data was
-- refreshed.

CREATE OR ALTER PROCEDURE [PLM].[usp_RunPLM_ItemGroup]
    @ItemGroup INT
AS
BEGIN
    SET NOCOUNT ON;

    -- The batch empties and refills the tables these steps read, and refreshes every group anyway.
    -- Only a test: holding the batch's lock would make a batch started meanwhile skip its run.
    IF APPLOCK_TEST('public', N'usp_RunPLM_Batch', 'Exclusive', 'Session') = 0
    BEGIN
        RAISERROR(N'usp_RunPLM_Batch is running and will refresh item group %d too: nothing done.', 16, 1, @ItemGroup);
        RETURN;
    END;

    -- What the batch's steps 70 and 80 would refresh for this group.
    SELECT DISTINCT [Group Locations] AS [Location]
    INTO #group_locations
    FROM [PLM].[vw_PLMItemGroupLocation]
    WHERE [Item Group] = @ItemGroup;

    SELECT DISTINCT [Inventory_base_ID], [PKID], [Item], [Location]
    INTO #link_locations
    FROM [PLM].[vw_PLMZDate]
    WHERE [Item Group] = @ItemGroup
      AND [Inventory_base_ID] IS NOT NULL;

    DECLARE @stale_group INT, @stale_link INT;

    DELETE R
    FROM [PLM].[PLMItemGroupBRRolling] AS R
    WHERE R.[Item Group] = @ItemGroup
      AND NOT EXISTS (SELECT 1 FROM #group_locations AS g WHERE g.[Location] = R.[Location]);
    SET @stale_group = @@ROWCOUNT;

    DELETE R
    FROM [PLM].[PLMItemBRRolling] AS R
    WHERE (R.[Item Group] = @ItemGroup
           OR R.[PKID] IN (SELECT [PKID] FROM [PLM].[ItemLink] WHERE [Item Group] = @ItemGroup))
      AND NOT EXISTS (SELECT 1 FROM #link_locations AS t
                      WHERE t.[Inventory_base_ID] = R.[Inventory_base_ID] AND t.[PKID] = R.[PKID]
                        AND t.[Item] = R.[Item] AND t.[Location] = R.[Location]);
    SET @stale_link = @@ROWCOUNT;

    DECLARE @Location VARCHAR(20), @Inventory_base_ID BIGINT, @PKID BIGINT, @log_id BIGINT,
            @group_calls INT = 0, @link_calls INT = 0, @errors INT = 0;

    DECLARE group_cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT [Location] FROM #group_locations ORDER BY [Location];
    OPEN group_cur;
    FETCH NEXT FROM group_cur INTO @Location;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT INTO [PLM].[PLMItemGroupBRRolling_Log] (item_group, location, status)
        VALUES (@ItemGroup, @Location, 'START');
        SET @log_id = SCOPE_IDENTITY();

        BEGIN TRY
            EXEC [PLM].[sp_PLM_PersistItemGroupBRRolling] @ItemGroup = @ItemGroup, @Location = @Location;

            UPDATE [PLM].[PLMItemGroupBRRolling_Log]
            SET status = 'SUCCESS',
                rows_after = (SELECT COUNT(*) FROM [PLM].[PLMItemGroupBRRolling]
                              WHERE [Item Group] = @ItemGroup AND [Location] = @Location),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END TRY
        BEGIN CATCH
            SET @errors += 1;
            UPDATE [PLM].[PLMItemGroupBRRolling_Log]
            SET status = 'ERROR',
                err_msg = CONCAT(
                    'Num:', ERROR_NUMBER(), '; Sev:', ERROR_SEVERITY(), '; State:', ERROR_STATE(),
                    '; Proc:', ISNULL(ERROR_PROCEDURE(), 'N/A'),
                    '; Line:', ERROR_LINE(), '; Msg:', ERROR_MESSAGE()
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END CATCH;

        SET @group_calls += 1;
        FETCH NEXT FROM group_cur INTO @Location;
    END;
    CLOSE group_cur;
    DEALLOCATE group_cur;

    DECLARE link_cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT DISTINCT [Inventory_base_ID], [PKID] FROM #link_locations ORDER BY [PKID], [Inventory_base_ID];
    OPEN link_cur;
    FETCH NEXT FROM link_cur INTO @Inventory_base_ID, @PKID;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT INTO [PLM].[PLMItemBRRolling_Log] (inventory_base_id, pkid, status)
        VALUES (@Inventory_base_ID, @PKID, 'START');
        SET @log_id = SCOPE_IDENTITY();

        BEGIN TRY
            EXEC [PLM].[sp_PLM_PersistItemBRRolling] @Inventory_base_ID = @Inventory_base_ID, @PKID = @PKID;

            UPDATE [PLM].[PLMItemBRRolling_Log]
            SET status = 'SUCCESS',
                rows_after = (SELECT COUNT(*) FROM [PLM].[PLMItemBRRolling]
                              WHERE Inventory_base_ID = @Inventory_base_ID AND PKID = @PKID),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END TRY
        BEGIN CATCH
            SET @errors += 1;
            UPDATE [PLM].[PLMItemBRRolling_Log]
            SET status = 'ERROR',
                err_msg = CONCAT(
                    'Num:', ERROR_NUMBER(), '; Sev:', ERROR_SEVERITY(), '; State:', ERROR_STATE(),
                    '; Proc:', ISNULL(ERROR_PROCEDURE(), 'N/A'),
                    '; Line:', ERROR_LINE(), '; Msg:', ERROR_MESSAGE()
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END CATCH;

        SET @link_calls += 1;
        FETCH NEXT FROM link_cur INTO @Inventory_base_ID, @PKID;
    END;
    CLOSE link_cur;
    DEALLOCATE link_cur;

    PRINT CONCAT('Item group ', @ItemGroup, ': ', @group_calls, ' group locations and ', @link_calls,
                 ' link locations recomputed; stale rows deleted: ', @stale_group,
                 ' PLMItemGroupBRRolling, ', @stale_link, ' PLMItemBRRolling.');
    IF @errors > 0
        RAISERROR(N'%d of those failed: see status ''ERROR'' in PLMItemGroupBRRolling_Log / PLMItemBRRolling_Log.', 16, 1, @errors);
END;
GO

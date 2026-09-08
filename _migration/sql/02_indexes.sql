/* Generated from LIVE PRIME by _migration/generate_ddl.py.
   Do not hand-edit - regenerate instead. */
USE [PLM];
GO

CREATE NONCLUSTERED INDEX [IX_BurnRateRefreshJob_ItemLink] ON [PLM].[burn_rate_refresh_job] ([item_link_id]);
GO
CREATE NONCLUSTERED INDEX [IX_ConflictError_Type] ON [PLM].[ConflictError] ([error_type]);
GO
CREATE NONCLUSTERED INDEX [IX_ConflictError_Item] ON [PLM].[ConflictError] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ConflictError_ReplaceItem] ON [PLM].[ConflictError] ([Replace Item]);
GO
ALTER TABLE [PLM].[DailyIssueOutQty] ADD CONSTRAINT [UQ_DailyIssueOutQty_Company_Location_Item_trxdate] UNIQUE NONCLUSTERED ([Company], [Location], [Item], [trx_date]);
GO
CREATE NONCLUSTERED INDEX [IX_DailyIssueOutQty_trx_date] ON [PLM].[DailyIssueOutQty] ([trx_date]);
GO
CREATE NONCLUSTERED INDEX [IX_DailyIssueOutQty_item] ON [PLM].[DailyIssueOutQty] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_DailyIssueOutQty_location] ON [PLM].[DailyIssueOutQty] ([Location]);
GO
CREATE NONCLUSTERED INDEX [IX_DailyIssueOutQty_location_item] ON [PLM].[DailyIssueOutQty] ([Location], [Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemGroup_Item] ON [PLM].[ItemGroup] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemGroup_ItemGroup] ON [PLM].[ItemGroup] ([Item Group]);
GO
CREATE UNIQUE NONCLUSTERED INDEX [UX_ItemGroupLink_Group_Link] ON [PLM].[ItemGroupLink] ([item_group_pkid], [item_link_id]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemGroupLink_Group] ON [PLM].[ItemGroupLink] ([item_group_pkid]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemGroupLink_ItemLink] ON [PLM].[ItemGroupLink] ([item_link_id]);
GO
CREATE UNIQUE NONCLUSTERED INDEX [UX_ItemLink_Item_Replace] ON [PLM].[ItemLink] ([Item Group], [Item], [Replace Item]) WHERE ([Replace Item] IS NOT NULL);
GO
CREATE UNIQUE NONCLUSTERED INDEX [UX_ItemLink_GroupItem_Discontinued] ON [PLM].[ItemLink] ([Item Group], [Item]) WHERE ([Replace Item] IS NULL);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLink_Item] ON [PLM].[ItemLink] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLink_ItemGroup] ON [PLM].[ItemLink] ([Item Group]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLink_ReplaceItem] ON [PLM].[ItemLink] ([Replace Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLink_Stage] ON [PLM].[ItemLink] ([Stage]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkArchived_Stage] ON [PLM].[ItemLinkArchived] ([Stage]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkArchived_Item] ON [PLM].[ItemLinkArchived] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkArchived_ItemGroup] ON [PLM].[ItemLinkArchived] ([Item Group]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkArchived_ReplaceItem] ON [PLM].[ItemLinkArchived] ([Replace Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkDeleted_ItemGroup] ON [PLM].[ItemLinkDeleted] ([Item Group]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkDeleted_ReplaceItem] ON [PLM].[ItemLinkDeleted] ([Replace Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkDeleted_Stage] ON [PLM].[ItemLinkDeleted] ([Stage]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLinkDeleted_Item] ON [PLM].[ItemLinkDeleted] ([Item]);
GO
ALTER TABLE [PLM].[ItemLinkWrike] ADD CONSTRAINT [UX_ItemLinkWrike_ItemLink] UNIQUE NONCLUSTERED ([item_link_id]);
GO
ALTER TABLE [PLM].[ItemLocations] ADD CONSTRAINT [UQ_ItemLocations_Location_Item] UNIQUE NONCLUSTERED ([Location], [Item]);
GO
ALTER TABLE [PLM].[ItemLocationsBR] ADD CONSTRAINT [UQ_ItemLocationsBR_Location_Item] UNIQUE NONCLUSTERED ([Location], [Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLocationsBR_Item] ON [PLM].[ItemLocationsBR] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLocationsBR_Location] ON [PLM].[ItemLocationsBR] ([Location]);
GO
CREATE NONCLUSTERED INDEX [IX_ItemLocationsBR_LocationType] ON [PLM].[ItemLocationsBR] ([LocationType]);
GO
ALTER TABLE [PLM].[ItemStartEndDate] ADD CONSTRAINT [UQ_InvItemStartEndDate_Company_Location_Item] UNIQUE NONCLUSTERED ([Company], [Location], [Item]);
GO
CREATE NONCLUSTERED INDEX [IX_InvItemStartEndDate_Item] ON [PLM].[ItemStartEndDate] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_InvItemStartEndDate_Location] ON [PLM].[ItemStartEndDate] ([Location]);
GO
CREATE NONCLUSTERED INDEX [IX_InvItemStartEndDate_Location_Item] ON [PLM].[ItemStartEndDate] ([Location], [Item]);
GO
ALTER TABLE [PLM].[PendingItems] ADD CONSTRAINT [UX_PendingItems_Link_ContractReplace] UNIQUE NONCLUSTERED ([item_link_id], [contract_id], [replace_item_pending]);
GO
CREATE NONCLUSTERED INDEX [IX_PendingItems_ReplaceItemPending] ON [PLM].[PendingItems] ([replace_item_pending]);
GO
CREATE NONCLUSTERED INDEX [IX_PendingItems_Status] ON [PLM].[PendingItems] ([status]);
GO
ALTER TABLE [PLM].[PLMItemBRRolling] ADD CONSTRAINT [UQ_PLMItemBRRolling_item_link_id] UNIQUE NONCLUSTERED ([Inventory_base_ID], [PKID]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemBRRolling_item_link_id] ON [PLM].[PLMItemBRRolling] ([PKID]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemBRRolling_InventoryBaseID] ON [PLM].[PLMItemBRRolling] ([Inventory_base_ID]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemBRRolling_Item] ON [PLM].[PLMItemBRRolling] ([Item]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemBRRolling_Location] ON [PLM].[PLMItemBRRolling] ([Location]);
GO
ALTER TABLE [PLM].[PLMItemGroupBRRolling] ADD CONSTRAINT [UQ_PLMItemGroupBRRolling_ItemGroup_Location_Company] UNIQUE NONCLUSTERED ([Item Group], [Location], [Company]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemGroupBRRolling_ItemGroup] ON [PLM].[PLMItemGroupBRRolling] ([Item Group]);
GO
CREATE NONCLUSTERED INDEX [IX_PLMItemGroupBRRolling_Location] ON [PLM].[PLMItemGroupBRRolling] ([Location]);
GO
CREATE NONCLUSTERED INDEX [IX_PLM_ProcessLog_Time] ON [PLM].[process_log] ([exec_start] DESC);
GO
CREATE NONCLUSTERED INDEX [IX_PLM_ProcessLog_Status] ON [PLM].[process_log] ([status], [exec_start] DESC) INCLUDE ([process_name]);
GO
CREATE NONCLUSTERED INDEX [ix_PLM_users_user_role] ON [PLM].[users] ([user_role]);
GO
CREATE UNIQUE NONCLUSTERED INDEX [ix_PLM_users_email] ON [PLM].[users] ([email]);
GO

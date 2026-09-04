/* Generated from LIVE PRIME by _migration/generate_ddl.py.
   Do not hand-edit - regenerate instead. */
USE [PLM];
GO

IF SCHEMA_ID('PLM') IS NULL EXEC('CREATE SCHEMA [PLM]');
GO

CREATE TABLE [PLM].[burn_rate_refresh_job] (
    [id] bigint IDENTITY(1,1) NOT NULL,
    [item_link_id] bigint NOT NULL,
    [status] varchar(20) NOT NULL,
    [message] varchar(500) NULL,
    [created_at] datetime NOT NULL,
    [started_at] datetime NULL,
    [finished_at] datetime NULL,
    CONSTRAINT [PK__burn_rat__3213E83F6B3C7914] PRIMARY KEY CLUSTERED ([id])
);
GO

CREATE TABLE [PLM].[ConflictError] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [item_link_id] bigint NULL,
    [Item Group] int NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Replace Item] varchar(250) NULL,
    [error_message] varchar(1000) NOT NULL,
    [error_type] varchar(100) NOT NULL,
    [create_dt] datetime NOT NULL,
    CONSTRAINT [PK__Conflict__5E028272B385B906] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ConflictErrorPendingItemAddition_log] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [item_link_id] bigint NOT NULL,
    [pending_pkid] bigint NOT NULL,
    [item] nvarchar(10) NOT NULL,
    [Item Group] int NULL,
    [side] char(1) NOT NULL,
    [create_dt] datetime NOT NULL CONSTRAINT [DF__ConflictE__creat__1B014832] DEFAULT (getdate()),
    [error_msg] nvarchar(4000) NOT NULL,
    CONSTRAINT [PK__Conflict__5E0282720CE0C6C7] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[DailyIssueOutQty] (
    [Inventory_base_ID] bigint NOT NULL,
    [Company] varchar(10) NOT NULL,
    [Location] varchar(50) NOT NULL,
    [Item] varchar(50) NOT NULL,
    [Lum] varchar(10) NOT NULL,
    [trx_date] date NOT NULL,
    [QtyInLum] int NULL,
    [create_date] date NULL,
    [z_date] date NULL,
    [existing_days] int NULL,
    CONSTRAINT [PK_DailyIssueOutQty] PRIMARY KEY CLUSTERED ([Inventory_base_ID], [trx_date])
);
GO

CREATE TABLE [PLM].[ItemGroup] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Item Group] int NOT NULL,
    [Side] varchar(1) NOT NULL,
    [create_dt] datetime NOT NULL,
    [update_dt] datetime NOT NULL,
    CONSTRAINT [PK__ItemGrou__5E02827236DD8069] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemGroupLink] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [item_group_pkid] bigint NOT NULL,
    [item_link_id] bigint NOT NULL,
    [create_dt] datetime NOT NULL CONSTRAINT [DF_ItemGroupLink_create_dt] DEFAULT (getdate()),
    CONSTRAINT [PK__ItemGrou__5E028272A8AB91B8] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemLink] (
    [Item Group] int NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Manufacturer Part Num] varchar(100) NULL,
    [Manufacturer] varchar(250) NULL,
    [Item Description] varchar(500) NULL,
    [Replace Item] varchar(250) NULL,
    [Replace Item Manufacturer Part Num] varchar(100) NULL,
    [Replace Item Manufacturer] varchar(250) NULL,
    [Replace Item Item Description] varchar(500) NULL,
    [Stage] varchar(100) NOT NULL,
    [Expected Go Live Date] date NULL,
    [CreateDT] datetime NOT NULL CONSTRAINT [DF__ItemLink__Create__6B9C4DD3] DEFAULT (getdate()),
    [UpdateDT] datetime NOT NULL CONSTRAINT [DF__ItemLink__Update__6C90720C] DEFAULT (getdate()),
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_ItemLink_Id] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemLink_copy] (
    [Item Group] int NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Manufacturer Part Num] varchar(100) NULL,
    [Manufacturer] varchar(250) NULL,
    [Item Description] varchar(500) NULL,
    [Replace Item] varchar(250) NULL,
    [Replace Item Manufacturer Part Num] varchar(100) NULL,
    [Replace Item Manufacturer] varchar(250) NULL,
    [Replace Item Item Description] varchar(500) NULL,
    [Stage] varchar(100) NOT NULL,
    [Expected Go Live Date] date NULL,
    [CreateDT] datetime NOT NULL,
    [UpdateDT] datetime NOT NULL,
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [copyDT] datetime NOT NULL
);
GO

CREATE TABLE [PLM].[ItemLinkArchived] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [Item Group] int NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Replace Item] varchar(250) NULL,
    [Manufacturer Part Num] varchar(100) NULL,
    [Manufacturer] varchar(100) NULL,
    [Item Description] varchar(500) NULL,
    [Replace Item Manufacturer Part Num] varchar(100) NULL,
    [Replace Item Manufacturer] varchar(100) NULL,
    [Replace Item Item Description] varchar(500) NULL,
    [Stage] varchar(100) NULL,
    [Expected Go Live Date] date NULL,
    [CreateDT] datetime NULL,
    [UpdateDT] datetime NULL,
    [item_link_id] bigint NOT NULL,
    [ArchivedDT] datetime NOT NULL,
    CONSTRAINT [PK__ItemLink__5E028272E82E4F0C] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemLinkDeleted] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [Item Group] int NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Replace Item] varchar(250) NULL,
    [Manufacturer Part Num] varchar(100) NULL,
    [Manufacturer] varchar(100) NULL,
    [Item Description] varchar(500) NULL,
    [Replace Item Manufacturer Part Num] varchar(100) NULL,
    [Replace Item Manufacturer] varchar(100) NULL,
    [Replace Item Item Description] varchar(500) NULL,
    [Stage] varchar(100) NULL,
    [Expected Go Live Date] date NULL,
    [CreateDT] datetime NULL,
    [UpdateDT] datetime NULL,
    [item_link_id] bigint NOT NULL,
    [DeletedDT] datetime NOT NULL,
    CONSTRAINT [PK__ItemLink__5E02827276447A20] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemLinkWrike] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [item_link_id] bigint NOT NULL,
    [Item] varchar(10) NOT NULL,
    [Replace Item] varchar(250) NULL,
    [Item Group] int NOT NULL,
    [Stage] varchar(100) NULL,
    [WrikeID1] varchar(50) NULL,
    [CreateDT1] datetime NULL,
    [UpdateDT1] datetime NULL,
    [CompleteDT1] datetime NULL,
    [Completed1] int NOT NULL,
    [WrikeID2] varchar(50) NULL,
    [CreateDT2] datetime NULL,
    [UpdateDT2] datetime NULL,
    [CompleteDT2] datetime NULL,
    [Completed2] int NOT NULL,
    [WrikeID3] varchar(50) NULL,
    [CreateDT3] datetime NULL,
    [UpdateDT3] datetime NULL,
    [CompleteDT3] datetime NULL,
    [Completed3] int NOT NULL,
    [WrikeID4] varchar(50) NULL,
    [CreateDT4] datetime NULL,
    [UpdateDT4] datetime NULL,
    [CompleteDT4] datetime NULL,
    [Completed4] int NOT NULL,
    [WrikeID5] varchar(50) NULL,
    [CreateDT5] datetime NULL,
    [UpdateDT5] datetime NULL,
    [CompleteDT5] datetime NULL,
    [Completed5] int NOT NULL,
    CONSTRAINT [PK__ItemLink__5E0282728FDD4634] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[ItemLocations] (
    [Inventory_base_ID] int NOT NULL,
    [Company] varchar(10) NOT NULL,
    [Location] varchar(255) NOT NULL,
    [LocationText] varchar(255) NULL,
    [LocationType] varchar(40) NULL,
    [PreferredBin] varchar(40) NULL,
    [Item] varchar(255) NOT NULL,
    [ItemDescription] varchar(255) NULL,
    [ItemType] varchar(40) NULL,
    [Active] varchar(5) NULL,
    [Discontinued] varchar(5) NULL,
    [VendorItem] varchar(100) NULL,
    [ManufacturerNumber] varchar(100) NULL,
    [DefaultBuyUOM] varchar(10) NULL,
    [BuyUOMMultiplier] numeric(18,4) NULL,
    [AutomaticPO] varchar(5) NULL,
    [StockUOM] varchar(10) NOT NULL,
    [UOMConversion] numeric(10,4) NULL,
    [DefaultTransactionUOM] varchar(10) NULL,
    [InventoryTransactionUOMMultiplier] numeric(10,4) NULL,
    [ReorderQuantityCode] varchar(40) NULL,
    [ReorderPoint] int NULL,
    [MaxOrderQty] int NULL,
    [MinOrderQty] int NULL,
    [OnHandQty] int NULL,
    [AvailableQty] int NULL,
    [OnOrderQty] int NULL,
    [UnitCostInStockUOM] numeric(18,4) NULL,
    [DerivedAverageCost] numeric(18,4) NULL,
    [report stamp] datetime NOT NULL,
    [create stamp] datetime NOT NULL,
    CONSTRAINT [PK_PLM_ItemLoc] PRIMARY KEY CLUSTERED ([Inventory_base_ID])
);
GO

CREATE TABLE [PLM].[ItemLocationsBR] (
    [Inventory_base_ID] int NOT NULL,
    [LocationType] varchar(40) NULL,
    [Company] varchar(10) NOT NULL,
    [Location] varchar(255) NOT NULL,
    [Item] varchar(255) NOT NULL,
    [br7] numeric(38,6) NULL,
    [br35] numeric(38,6) NULL,
    [br91] numeric(38,6) NULL,
    [br365] numeric(38,6) NULL,
    [issued_count_365] int NULL,
    [OrderQty90_EA] numeric(38,4) NULL,
    [ReceivedQty90_EA] numeric(38,4) NULL,
    [CancelQty90_EA] numeric(38,4) NULL,
    [ReqQty90_EA] numeric(18,4) NULL,
    CONSTRAINT [PK_PLM_ItemLocBR] PRIMARY KEY CLUSTERED ([Inventory_base_ID])
);
GO

CREATE TABLE [PLM].[ItemStartEndDate] (
    [Inventory_base_ID] bigint NOT NULL,
    [Company] varchar(10) NOT NULL,
    [Location] varchar(20) NOT NULL,
    [Item] varchar(10) NOT NULL,
    [create_date] date NOT NULL,
    [z_date] date NOT NULL,
    CONSTRAINT [PK_InventoryBaseID] PRIMARY KEY CLUSTERED ([Inventory_base_ID])
);
GO

CREATE TABLE [PLM].[PastYearRequestersCount] (
    [Location] varchar(20) NOT NULL,
    [Item] varchar(10) NOT NULL,
    [requester_count] int NULL,
    CONSTRAINT [PK_PastYearRequestersCount_Location_Item] PRIMARY KEY CLUSTERED ([Location], [Item])
);
GO

CREATE TABLE [PLM].[PendingItems] (
    [PKID] bigint IDENTITY(1,1) NOT NULL,
    [item_link_id] bigint NOT NULL,
    [replace_item_pending] varchar(250) NOT NULL,
    [status] varchar(20) NOT NULL,
    [contract_id] varchar(50) NOT NULL,
    [mfg_part_num] varchar(100) NOT NULL,
    [replace_item_immast] varchar(10) NOT NULL CONSTRAINT [DF_PendingItems_replace_item_immast] DEFAULT (''),
    [create_dt] datetime NOT NULL,
    [update_dt] datetime NOT NULL,
    CONSTRAINT [PK__PendingI__5E028272584DE83A] PRIMARY KEY CLUSTERED ([PKID])
);
GO

CREATE TABLE [PLM].[PLMItemBRRolling] (
    [Inventory_base_ID] bigint NOT NULL,
    [PKID] bigint NOT NULL,
    [Company] varchar(10) NOT NULL,
    [Location] varchar(20) NOT NULL,
    [Item] varchar(10) NOT NULL,
    [z_date] date NULL,
    [existing_days] int NULL,
    [LocationType] varchar(40) NULL,
    [Z_date_to_use] date NULL,
    [BRCalcStatus] varchar(12) NOT NULL,
    [BRCalcType] varchar(12) NOT NULL,
    [Item Group] int NOT NULL,
    [Side] varchar(1) NOT NULL,
    [days_overlap] int NULL,
    [rolling_daily_avg_7] numeric(38,6) NULL,
    [rolling_daily_median_7] float(53) NULL,
    [rolling_daily_avg_60] numeric(38,6) NULL,
    [rolling_daily_median_60] float(53) NULL,
    [create_ts] datetime2(7) NOT NULL,
    CONSTRAINT [PK_InventoryBaseID_ItemLinkID] PRIMARY KEY CLUSTERED ([Inventory_base_ID], [PKID])
);
GO

CREATE TABLE [PLM].[PLMItemBRRolling_Log] (
    [run_id] bigint IDENTITY(1,1) NOT NULL,
    [inventory_base_id] bigint NOT NULL,
    [pkid] bigint NOT NULL,
    [start_ts] datetime2(3) NOT NULL CONSTRAINT [DF__PLMItemBR__start__2CCAF2B2] DEFAULT (sysdatetime()),
    [end_ts] datetime2(3) NULL,
    [status] varchar(20) NULL,
    [rows_after] int NULL,
    [err_msg] nvarchar(4000) NULL,
    CONSTRAINT [PK__PLMItemB__7D3D901B0E0CC57B] PRIMARY KEY CLUSTERED ([run_id])
);
GO

CREATE TABLE [PLM].[PLMItemGroupBRRolling] (
    [Item Group] int NOT NULL,
    [Location] varchar(50) NOT NULL,
    [Company] varchar(10) NOT NULL,
    [LocationType] varchar(40) NULL,
    [rolling_daily_avg_7] numeric(38,6) NULL,
    [rolling_daily_median_7] float(53) NULL,
    [rolling_daily_avg_60] numeric(38,6) NULL,
    [rolling_daily_median_60] float(53) NULL,
    [create_ts] datetime2(7) NOT NULL,
    CONSTRAINT [PK_ItemGroup_Location_Company] PRIMARY KEY CLUSTERED ([Item Group], [Location], [Company])
);
GO

CREATE TABLE [PLM].[PLMItemGroupBRRolling_Log] (
    [run_id] bigint IDENTITY(1,1) NOT NULL,
    [item_group] int NOT NULL,
    [location] nvarchar(64) NOT NULL,
    [start_ts] datetime2(3) NOT NULL CONSTRAINT [DF__PLMItemGr__start__224D643F] DEFAULT (sysdatetime()),
    [end_ts] datetime2(3) NULL,
    [status] varchar(20) NULL,
    [rows_after] int NULL,
    [err_msg] nvarchar(4000) NULL,
    CONSTRAINT [PK__PLMItemG__7D3D901B00FB6ED3] PRIMARY KEY CLUSTERED ([run_id])
);
GO

CREATE TABLE [PLM].[process_log] (
    [pkid] bigint IDENTITY(1,1) NOT NULL,
    [process_name] sysname NOT NULL,
    [exec_start] datetime2(3) NOT NULL,
    [exec_end] datetime2(3) NULL,
    [status] varchar(16) NOT NULL CONSTRAINT [DF__process_l__statu__7A3F72E5] DEFAULT ('Unknown'),
    [err_msg] nvarchar(4000) NULL,
    [duration_ms] bigint NULL,
    CONSTRAINT [PK__process___40A64C0B10912D03] PRIMARY KEY CLUSTERED ([pkid])
);
GO

CREATE TABLE [PLM].[users] (
    [user_id] int IDENTITY(1,1) NOT NULL,
    [email] varchar(255) NOT NULL,
    [name] varchar(120) NULL,
    [user_role] varchar(50) NOT NULL CONSTRAINT [DF__users__user_role__07446848] DEFAULT ('user'),
    [pw_hash] varchar(255) NOT NULL,
    [is_active] bit NOT NULL,
    [created_at] datetime NOT NULL,
    [last_login_at] datetime NULL,
    [reset_code] varchar(10) NULL,
    [reset_code_expiry] datetime NULL,
    [approved_by] varchar(255) NULL,
    [approved_at] datetime NULL,
    [disabled_by] varchar(255) NULL,
    [disabled_at] datetime NULL,
    CONSTRAINT [PK__users__B9BE370F0282AE8A] PRIMARY KEY CLUSTERED ([user_id])
);
GO

CREATE TABLE [PLM].[WrikeTask] (
    [Original_Wrike_ID] varchar(50) NOT NULL,
    [Wrike_TenDigit_ID] varchar(10) NOT NULL,
    [Title] varchar(255) NOT NULL,
    [Has_Attachment] varchar(1) NOT NULL,
    [Assignee] varchar(255) NULL,
    [Create_Date] datetime NOT NULL,
    [Complete_Date] datetime NULL,
    [Update_Date] datetime NOT NULL,
    [Misc] varchar(max) NULL,
    [Row_Update_Time] datetime NOT NULL,
    CONSTRAINT [PK__WrikeTas__1E4EB116D3F3B1F8] PRIMARY KEY CLUSTERED ([Original_Wrike_ID], [Wrike_TenDigit_ID])
);
GO


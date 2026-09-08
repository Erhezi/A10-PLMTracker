/* Generated from LIVE PRIME by _migration/generate_ddl.py.
   Do not hand-edit - regenerate instead. */
USE [PLM];
GO

-- ===== TIER 1 =====
CREATE OR ALTER view [PLM].[vw_365Day_Requesters] as
(
select rl.RequestingLocation, Item, rl.Requester, rl.RequesterName, [Requisition.FD5], r.EmailAddress, RequestsCount
from(
select RequestingLocation, Item, Requester, RequesterName, [Requisition.FD5], count(1) as RequestsCount
from PLMPreprocessorShared.infor.[REQUISITION_LINE]
where company = '3000'
and ApprovedRejectedDate between  (try_convert(date, getdate() - 366)) and try_convert(date, getdate())
and ItemType in ('Inventoried', 'Non Stock')
and [Status] = 'Processed'
and (RequestingLocation like 'p%' or RequestingLocation like 'I%' or RequestingLocation like 'R%')
group by RequestingLocation, Item, Requester, RequesterName, [Requisition.FD5]) [rl]
left join PLMPreprocessorShared.infor.[MDM_REQUESTER] [r]
on rl.Requester = r.Requester
where rl.Requester <> '60000002'
)
GO

CREATE OR ALTER view [PLM].[vw_90Day_PO] as
(
SELECT case when InventoryFD1 = '' then 'Non Storeroom' else 'Storeroom' end as [OrderToStoreroom],
case when TrasientInventoryLocation like 'I%STRM' THEN TrasientInventoryLocation else 'Others' end as  [Location],
Company,
TrasientInventoryLocation, pol.Item, EnteredBuyUOM, EnteredBuyUOMMultiplier, [Item.StockUOM], uom.UOMConversion,
Quantity, ReceivedQuantity, CancelQuantity,
quantity * try_convert(numeric, EnteredBuyUOMMultiplier) as OrderQty_EA, 
ReceivedQuantity * try_convert(numeric, EnteredBuyUOMMultiplier) as ReceivedQty_EA, 
CancelQuantity * try_convert(numeric, EnteredBuyUOMMultiplier) as CancelQty_EA,
IsOpenForReceivingIncludingUnreleased,
POReleaseDate, PO, POLine, PurchaseOrderLine, Vendor, VendorName, [Index], IndexText, BusinessArea, BusinessAreaText,
Requisition, RequisitionLine, [PO.RequesterName]
FROM PLMPreprocessorShared.infor.[PURCHASEORDER_LINE] [pol]
left join PLMPreprocessorShared.infor.[MDM_ITEMUOM] [uom]
on pol.item = uom.item
and pol.[item.stockUOM] = uom.UOM
WHERE POReleaseDate BETWEEN (try_convert(date, getdate() - 91)) and try_convert(date, getdate())
AND pol.ItemType in ('Inventoried', 'Non Stock')
and company = '3000'
and EXC_FLAG = 'default'
)
GO

CREATE OR ALTER view [PLM].[vw_ContractItem] AS
select contract_id, manufacturer, mfg_part_num, search_shadow, item_description, item_type, item, long_item_number,
is_mhs, last_update_date
from(
select *, row_number() over (partition by contract_id, manufacturer, mfg_part_num order by item desc) as rk
from(
select distinct 
WorkingContractID as contract_id, 
m.ManufacturerName as manufacturer, 
ManufacturerNumber as mfg_part_num,
concat(DerivedStrippedManufacturerNumber,'|',DerivedStrippedVendorItem, '|', ItemNumber) as search_shadow, 
ItemDescription as item_description, 
ItemType as item_type, 
IIF(itemtype = 'Itemmast', ItemNumber, '') as item,
IIF(itemtype = 'Special', ItemNumber, '') as long_item_number,
(select max(try_convert(date, [update stamp])) from PLMPreprocessorShared.infor.[CONTRACTLINE]) as last_update_date,
iif([Contract.MMAHSOrganizationEID] = '105188574', 'Yes', 'No') as is_mhs
from PLMPreprocessorShared.infor.[CONTRACTLINE] [c]
left join PLMPreprocessorShared.infor.[MDM_MANUFACTURER_NAME] [m]
on c.Manufacturer = m.Manufacturer
)[x]
)[xx]
where rk = 1;
GO

CREATE OR ALTER view [PLM].[vw_Item] AS
SELECT 
i.Item as item,
Active as is_active,
Discontinued as is_discontinued,
ManufacturerDescription as manufacturer,
ManufacturerNumber as mfg_part_num,
[Description] as item_description,
coalesce(Company3000, 'No') as company_3000,
[ReportDate] as last_update_date
from PLMPreprocessorShared.infor.[MDM_ITEM] [i]
left join (select distinct Item, 'Yes' as Company3000 FROM PLM.ItemLocations) [il]
on I.ITEM = IL.ITEM;
GO

CREATE OR ALTER VIEW PLM.vw_ItemReplacementCardinality
AS
WITH link_base AS (
    -- Deduplicate raw links so duplicates don't inflate counts
    SELECT DISTINCT [Item Group], Item, [Replace Item]
    FROM PLM.ItemLink
    -- WHERE is_active = 1   -- uncomment if you have an active flag
),
deg_item AS (
    SELECT [Item Group], Item, COUNT(*) AS links_per_item
    FROM link_base
    GROUP BY [Item Group], Item
),
deg_repl AS (
    SELECT [Item Group], [Replace Item], COUNT(*) AS links_per_repl
    FROM link_base
    GROUP BY [Item Group], [Replace Item]
),
group_rollup AS (
    SELECT
        lb.[Item Group],
        COUNT(*)                           AS num_links,
        COUNT(DISTINCT lb.Item)         AS num_items,
        COUNT(DISTINCT lb.[Replace Item])  AS num_replacements,
        MAX(di.links_per_item)             AS max_links_per_item,
        MAX(dr.links_per_repl)             AS max_links_per_repl,
        SUM(CASE WHEN di.links_per_item > 1 THEN 1 ELSE 0 END) AS items_with_multi,
        SUM(CASE WHEN dr.links_per_repl > 1 THEN 1 ELSE 0 END) AS replacements_with_multi
    FROM link_base lb
    JOIN deg_item di
      ON di.[Item Group] = lb.[Item Group] AND di.Item = lb.Item
    JOIN deg_repl dr
      ON dr.[Item Group] = lb.[Item Group] AND dr.[Replace Item] = lb.[Replace Item]
    GROUP BY lb.[Item Group]
)
SELECT
    gr.[Item Group] as group_id,
    gr.num_links,
    gr.num_items,
    gr.num_replacements,
    gr.max_links_per_item,
    gr.max_links_per_repl,
    gr.items_with_multi,
    gr.replacements_with_multi,
    CASE
        WHEN gr.max_links_per_item = 1 AND gr.max_links_per_repl = 1 THEN '1-1'
        WHEN gr.max_links_per_item > 1  AND gr.max_links_per_repl = 1 THEN '1-many'
        WHEN gr.max_links_per_item = 1  AND gr.max_links_per_repl > 1 THEN 'many-1'
        WHEN gr.max_links_per_item > 1  AND gr.max_links_per_repl > 1 THEN 'many-many'
        ELSE 'undetermined'
    END AS relation_type
FROM group_rollup gr;
GO

CREATE OR ALTER view PLM.vw_ItemUOM AS 
select Item, UOM, UOMConversion, ValidForInventoryTransaction, [Item.Active]
from PLMPreprocessorShared.infor.[MDM_ITEMUOM]
GO

CREATE OR ALTER view [PLM].[vw_PLMDailyIssueOutQty] as
with a as(
select Location, Item, QtyInLum, Inventory_base_ID, trx_date
from PLM.DailyIssueOutQty
),
b as(
select distinct Item, [Item Group], PKID
from(
select [Item Group], Item, PKID
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition', 'Tracking - Discontinued', 'Pending Item Number')
union all
select [Item Group], [Replace Item] as Item, PKID
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition')
) [x]
)

select a.*, b.[Item Group], b.PKID
from a join b
on a.Item = b.Item
GO

CREATE OR ALTER view [PLM].[vw_PLMItemCommodityCode] as 
with base as(
SELECT x.Item, x.Manufacturer, [Item Description], i.[CommodityCode.CcDescription], i.CommodityCode,
[Replace Item], [Replace Item Manufacturer], [Replace Item Item Description], [Item Group]
FROM plm.ItemLink [x]
left join PLMPreprocessorShared.infor.[MDM_ITEM] [i]
on x.Item = i.Item
)
SELECT [Item Group], Item, Manufacturer, [Item Description], CommodityCode, [CommodityCode.CcDescription],
concat([Item Description],'|',[Commoditycode.ccDescription]) as search_shadow_desc
FROM base
union all
select [Item Group], [Replace Item], [Replace Item Manufacturer], [Replace Item Item Description], CommodityCode, [CommodityCode.CcDescription],
concat([Item Description],'|',[Commoditycode.ccDescription]) as search_shadow_desc
from base
where [Replace Item] is not null
GO

CREATE OR ALTER view [PLM].[vw_PLMItemGroupLocation] as
select distinct x.[Item Group], y.[Company],
y.[Location] as [Group Locations], LocationType, y.LocationText
from(
select [Item Group], Item
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition', 'Tracking - Discontinued', 'Pending Item Number')
union all
select [Item Group], [Replace Item] as Item
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition')
)[x]
left join (
select distinct Item, [Location], [LocationType], [Company], [LocationText]
from PLM.ItemLocations) [y]
on x.Item = y.Item
where Company  = '3000'
GO

CREATE OR ALTER VIEW PLM.vw_PLMPendingItemsExport as
with a as(
select contract_id, mfg_part_num, item_link_id
from plm.PendingItems
where status = 'Pending'
),
b as (
select WorkingContractID, ManufacturerNumber, VendorItem, ItemDescription, BaseCost, UOM, DerivedUOMConversion, EffectiveDate, ExpirationDate
from PLMPreprocessorShared.infor.[CONTRACTLINE]
where [Contract.ContractStatus] = 'Active'
and [Contract.OnHold] = 'No'
and OnHold = 'No'
and ContractLineState = 'Active'
and ActiveLine = 'Yes'
and ExpirationDate >= getdate()
)

select a.*, b.*
from a join b
on a.contract_id = b.workingcontractid
and a.mfg_part_num = b.manufacturernumber
GO

CREATE OR ALTER view PLM.vw_orphan_node as(

select ig.PKID, item, side, igl.item_link_id
from plm.ItemGroup [ig] 
full outer join plm.ItemGroupLink [igl]
on ig.PKID = igl.item_group_pkid
where item_link_id is null or ig.pkid is null
)
GO

-- ===== TIER 2 =====
CREATE OR ALTER view PLM.vw_PLMReplacementActiveStatus as (
select [Replace Item], [Item Group], PKID, is_active
from plm.ItemLink [il]
left join (select Item, is_active from plm.vw_Item) [i]
on il.[Replace Item] = i.item)
GO

CREATE OR ALTER view [PLM].[vw_PLMTrackerHead] as
select link.PKID, link.Stage, link.[Item Group], link.Item, [Replace Item], 
loc.[Group Locations], loc.LocationText, LocationType, Company, CreateDT, UpdateDT
from PLM.ItemLink [link]
left join PLM.vw_PLMItemGroupLocation [loc]
on link.[Item Group] = loc.[Item Group]
GO

-- ===== TIER 3 =====
CREATE OR ALTER view [PLM].[vw_PLMTrackerBase] as
with a as(
select il.*, br.br7, br.br35, br.br91, br.br365, br.issued_count_365, br.OrderQty90_EA, br.ReqQty90_EA
from PLM.ItemLocations [il]
left join (
select * from PLM.ItemLocationsBR) [br]
on il.Inventory_base_ID = br.Inventory_base_ID
),
b1 as(
select distinct PKID, Item, Location, BRCalcStatus, BRCalcType, rolling_daily_avg_7, rolling_daily_avg_60
from PLM.PLMItemBRRolling
),
b2 as(
select [Item Group], [Location], rolling_daily_avg_7, rolling_daily_avg_60
from PLM.PLMItemGroupBRRolling
),
i as(
select item.Item, item.StockUOM, uom.UOMConversion, DefaultBuyUOM, DefaultBuyUOMMultiplier, ManufacturerNumber, 
DefaultInventoryTransactionUOM, DefaultInventoryTransactionUOMMultiplier, [Description] as ItemDescription,
CommodityCode, [CommodityCode.CcDescription]
from PLMPreprocessorShared.infor.[MDM_ITEM] [item]
left join (select Item, UOM, UOMConversion from PLMPreprocessorShared.infor.[MDM_ITEMUOM]) [uom]
on item.item = uom.item and item.StockUOM = uom.UOM
where active = 'Yes'
),
c as(
select Stage, PKID, [Item Group], Item, [Replace Item], 
coalesce([Group Locations], 'unknown') [Group Locations], 
coalesce(LocationType, 'unknown') [LocationType],
Company, LocationText
from PLM.vw_PLMTrackerHead [th]
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition', 'Tracking - Discontinued', 'Pending Item Number')
)

select c.[Stage], c.[PKID], c.[Item Group], c.[Group Locations], c.LocationText, c.LocationType, c.Company,
coalesce(b2.rolling_daily_avg_7, 0.0) as br7_rolling_itemgroup,
coalesce(b2.rolling_daily_avg_60, 0.0) as br60_rolling_itemgroup,
b1.BRCalcStatus as br_calc_status, 
b1.BRCalcType as br_calc_type,
case when a2.[Location] is null and a.[Location] is not null and c.Stage <> 'Tracking - Discontinued' then 'Create'
     when a2.[Location] is not null and a.[Location] is null then 'RI Only'
	 when c.Stage = 'Tracking - Discontinued' then 'Mute'
	 else 'Update' end as [action], 
c.Item, 
a.[Location], 
a.Inventory_base_ID, 
a.[PreferredBin],
a.[ItemDescription],
case when c.Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition') then
	concat('REPLACED BY ITEM #', try_convert(varchar(6), c.[Replace Item]), ' MFG #', try_convert(varchar(150), i.ManufacturerNumber))
	 when c.Stage = 'Tracking - Discontinued' then
	'ITEM DISCONTINUED, NO REPLACEMENT'
	 when c.Stage = 'Pending Item Number' then
	concat('REPLACED BY ITEM #PENDING', ' MFG #', try_convert(varchar(150), i.ManufacturerNumber))
	 else ''
	 end
	[ItemDescription2], 
a.ManufacturerNumber,
a.Active,
a.Discontinued,
a.AutomaticPO,
a.StockUOM,
a.UOMConversion,
a.DefaultBuyUOM, 
a.BuyUOMMultiplier,
a.DefaultTransactionUOM,
a.InventoryTransactionUOMMultiplier as TransactionUOMMultiplier,
a.ReorderQuantityCode,
a.ReorderPoint,
a.MaxOrderQty,
a.MinOrderQty,
a.AvailableQty,
a.UnitCostInStockUOM,
coalesce(b1.rolling_daily_avg_7, 0.0) as br7_rolling_item,
coalesce(b1.rolling_daily_avg_60, 0.0) as br60_rolling_item,
a.br7,
a.br35,
a.br91,
a.br365,
a.issued_count_365, 
a.OrderQty90_EA,
a.ReqQty90_EA,
c.[Replace Item], 
a2.[Location] as [Location_ri],
a2.Inventory_base_ID as [Inventory_base_ID_ri], 
a2.[PreferredBin] as PreferredBin_ri,
i.[ItemDescription] as [ItemDescription_ri], --from i (item table)
i.ManufacturerNumber as [ManufacturerNumber_ri], --from i (item table)
a2.Active as Active_ri,
a2.Discontinued as Discontinued_ri,
a2.AutomaticPO as AutomaticPO_ri,
i.StockUOM as StockUOM_ri, --i table
i.UOMConversion as UOMConversion_ri, --i table
i.DefaultBuyUOM as DefaultBuyUOM_ri, --i table
i.DefaultBuyUOMMultiplier as BuyUOMMultiplier_ri, --i table
a2.DefaultTransactionUOM as DefaultTransactionUOM_ri, --location table
a2.InventoryTransactionUOMMultiplier as TransactionUOMMultiplier_ri, --location table (this is not the item level one, it is based on itemloc's tranUOM)
uom.UOM as MatchedTransactionUOM_ri, -- uom match replace item to source item uom
uom.UOMConversion as MatchedTransactionUOMMultiplier_ri, -- uom match replace item to source item uom
a2.ReorderQuantityCode as ReorderQuantityCode_ri,
a2.ReorderPoint as ReorderPoint_ri,
a2.MaxOrderQty as MaxOrderQty_ri,
a2.MinOrderQty as MinOrderQty_ri,
a2.AvailableQty as AvailableQty_ri,
a2.UnitCostInStockUOM as UnitCostInStockUOM_ri,
coalesce(b12.rolling_daily_avg_7, 0.0) as br7_rolling_item_ri,
coalesce(b12.rolling_daily_avg_60, 0.0) as br60_rolling_item_ri,
a2.br7 as br7_ri,
a2.br35 as br35_ri,
a2.br91 as br91_ri,
a2.br365 as br365_ri,
a2.issued_count_365 as issued_count_365_ri, 
a2.OrderQty90_EA as OrderQty90_EA_ri,
a2.ReqQty90_EA as ReqQty90_EA_ri
from c
left join a
on c.item = a.Item and c.[Group Locations] = a.[Location]
left join a [a2]
on c.[Replace Item] = a2.Item  and c.[Group Locations] = a2.[Location]
left join b1
on c.item = b1.item and c.[Group Locations] = b1.[Location] and c.PKID = b1.PKID
left join b1 [b12]
on c.[Replace Item] = b12.Item and c.[Group Locations] = b12.Location and c.PKID = b12.PKID
left join b2
on c.[Item Group] = b2.[Item Group] and c.[Group Locations] = b2.Location
left join i
on c.[Replace Item] = i.item
left join (select Item, UOM, UOMConversion from PLMPreprocessorShared.infor.[MDM_ITEMUOM]) [uom]
on c.[Replace Item] = uom.Item and a.DefaultTransactionUOM = uom.UOM
GO

CREATE OR ALTER VIEW [PLM].[vw_PLMZDate] as
with base as(
select *,
case when days_overlap is null then 'KeepZ'
     when days_overlap >= -180 and days_to_start >= 90 then 'ReplaceZCDR'
	 else 'GroupBR'
	 end as BRCalcType,
case when days_overlap >= -180 and days_to_start >= 90 then create_date_ri
	 else z_date
	 end as PLM_Zdate,
case when createDT > base_data_last_update and stage <> 'Pending Item Number' then 'New - ADD'
     when updateDT > base_data_last_update and stage = 'Pending Item Number' then 'New - UPDATE'
	 else 'Exsiting' end as [BRCalcStatus]
from(
select th.*, d1.create_date, d1.z_date, d2.create_date as create_date_ri, d2.z_date as z_date_ri,
datediff(day, d1.z_date, d2.create_date) as days_overlap,
datediff(day, getdate() - 365, d2.create_date) as days_to_start,
(select max(exec_end) from PLM.process_log) as base_data_last_update
from PLM.vw_PLMTrackerHead [th]
left join PLM.ItemStartEndDate [d1]
on th.Item = d1.Item and th.[Group Locations] = d1.[Location]
left join PLM.ItemStartEndDate [d2]
on th.[Replace Item] = d2.Item and th.[Group Locations] = d2.[Location]
)[tmp]
),
transformed as(
SELECT *
FROM(
select [Group Locations] as [Location], [Item Group], Item, LocationType, Company,
BRCalcType, PLM_Zdate, BRCalcStatus, days_overlap, days_to_start, PKID
from base
union all 
select [Group Locations] as [Location], [Item Group], [Replace Item] as Item, LocationType, Company,
BRCalcType, z_date_ri as PLM_Zdate, BRCalcStatus, days_overlap, days_to_start, PKID
from base
)[x]
where PLM_Zdate IS NOT NULL
)
select [il].Inventory_base_ID, t.*
from transformed [t]
left join PLM.ItemLocations [il]
on t.Item = il.Item
and t.Location = il.Location
and t.Company = il.Company
GO

-- ===== TIER 4 =====
CREATE OR ALTER VIEW [PLM].[vw_PLMQty] as
with base as(
select [Company], [Location], il.[Item], (AvailableQty * UOMConversion) AS AvailableQty, il.[update stamp]
from PLMPreprocessorShared.infor.[ITEM_LOCATION] [il]
left join PLMPreprocessorShared.infor.[MDM_ITEMUOM] [iuom]
on il.Item = iuom.Item and il.StockUOM = iuom.UOM
where LocationType = 'Inventory Location'
and [Location] like 'I%'
and company = '3000'
and il.[update stamp] >= getdate() - 366
),
a as(
select base.[Location], base.[Item], base.AvailableQty, id.[Inventory_base_ID], [update stamp]
from base
left join (Select Company, Location, item, Inventory_base_ID From PLM.ItemLocations) [id]
on base.Company = id.Company
and base.Location = id.Location
and base.Item = id.Item
),
b as(
select distinct Item, [Item Group], PKID
from(
select [Item Group], Item, PKID
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition', 'Tracking - Discontinued', 'Pending Item Number')
union all
select [Item Group], [Replace Item] as Item, PKID
from PLM.ItemLink
where Stage in ('Pending Clinical Readiness', 'Tracking - Item Transition')
) [x]
)

select a.*, b.[Item Group], b.PKID, zt.PLM_Zdate
from a join b
on a.Item = b.Item
join (select Inventory_base_ID, PKID, PLM_Zdate from PLM.vw_PLMZDate) [zt]
on a.Inventory_base_ID = zt.Inventory_base_ID
and b.PKID = zt.PKID
GO


/* Generated from LIVE PRIME by _migration/generate_ddl.py.
   Do not hand-edit - regenerate instead. */
USE [PLM];
GO

-- Run AFTER the data load (see copy_data.py).

ALTER TABLE [PLM].[burn_rate_refresh_job] WITH CHECK ADD CONSTRAINT [FK__burn_rate__item___6A931B01]
    FOREIGN KEY ([item_link_id]) REFERENCES [PLM].[ItemLink] ([PKID])
    ON DELETE CASCADE;
GO

ALTER TABLE [PLM].[ConflictError] WITH CHECK ADD CONSTRAINT [FK__ConflictE__item___0C5E2320]
    FOREIGN KEY ([item_link_id]) REFERENCES [PLM].[ItemLink] ([PKID])
    ON DELETE CASCADE;
GO

ALTER TABLE [PLM].[ItemLinkWrike] WITH CHECK ADD CONSTRAINT [FK__ItemLinkW__item___4749DEC4]
    FOREIGN KEY ([item_link_id]) REFERENCES [PLM].[ItemLink] ([PKID])
    ON DELETE CASCADE;
GO

ALTER TABLE [PLM].[ItemGroupLink] WITH CHECK ADD CONSTRAINT [FK_ItemGroupLink_ItemGroup]
    FOREIGN KEY ([item_group_pkid]) REFERENCES [PLM].[ItemGroup] ([PKID])
    ON DELETE CASCADE;
GO

ALTER TABLE [PLM].[ItemGroupLink] WITH CHECK ADD CONSTRAINT [FK_ItemGroupLink_ItemLink]
    FOREIGN KEY ([item_link_id]) REFERENCES [PLM].[ItemLink] ([PKID])
    ON DELETE CASCADE;
GO

ALTER TABLE [PLM].[PendingItems] WITH CHECK ADD CONSTRAINT [FK_PendingItems_ItemLink]
    FOREIGN KEY ([item_link_id]) REFERENCES [PLM].[ItemLink] ([PKID])
    ON DELETE CASCADE;
GO


# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class SaleOrder(models.Model):
    """Inherit the Sale Order model to include a relationship with the Fleet
    Vehicle model."""
    _inherit = 'sale.order'

    work_order_count = fields.Integer(string="Work Order Count",
                                      help="Count of the work orders")
    has_work_order = fields.Boolean(
        string="Has Work Order",
        compute="_compute_has_work_order",
        help='Checking has work order.'
    )
    has_any_work_order = fields.Boolean(
        string="Has Any Work Order",
        compute="_compute_has_any_work_order",
        help="Indicates if the order has any work orders, regardless of their state."
    )

    invoiced_amount = fields.Monetary(
        string="Invoiced Amount",
        compute="_compute_invoiced_amount",
        store=True,
        currency_field="currency_id"
    )

    @api.depends('invoice_ids.amount_total', 'invoice_ids.state')
    def _compute_invoiced_amount(self):
        for order in self:
            # Sum the total amount from posted invoices (not drafts)
            invoices = order.invoice_ids.filtered(
                lambda inv: inv.state in ['posted'])
            order.invoiced_amount = sum(invoices.mapped('amount_total'))

    @api.depends('work_order_count')
    def _compute_has_work_order(self):
        """ Function for computing has work order."""
        for order in self:
            order.has_work_order = self.env['work.order'].search_count(
                [('sale_order_id', '=', order.id), ('state', '!=', 'cancel')]) > 0

    @api.depends('work_order_count')
    def _compute_has_any_work_order(self):
        """Compute if the order has any work orders, including canceled ones."""
        for order in self:
            order.has_any_work_order = self.env['work.order'].search_count(
                [('sale_order_id', '=', order.id)]) > 0

    # @api.model
    # def update_work_order(self):
    #     work_orders = [
    #         "0125020025-01", "0325020054-01", "1125020038-01",
    #         "0325020045-01", "0125020022-01", "1325020009-01",
    #         "0825020012-01", "1125020020-01", "1325020008-01",
    #         "1125020018-01", "0525020004-01", "0325020028-01",
    #         "0325020027-01", "0325020025-01", "0325020023-01",
    #         "0525020003-01", "0325020019-01", "0325020018-01",
    #         "0325020009-01",
    #     ]
    #     for i in work_orders:
    #         rec = self.env['work.order'].sudo().search([
    #             ('name', '=', i)
    #         ])
    #         if rec:
    #             rec.write({'state': 'delivered'})

    def action_create_work_order(self):
        """ Function for creating work order."""
        existing_work_order = self.env['work.order'].sudo().search([
            ('sale_order_id', '=', self.id),
            ('work_order_type', '=', 'product_service'),
            ('state', '!=', 'cancel'),
        ])
        if existing_work_order:
            raise ValidationError('Already a product service work order exists for this sale order.')
        work_order = self.env['work.order'].sudo().create({
            'sale_order_id': self.id,
            'customer_id': self.partner_id.id,
            'work_order_type': 'product_service',
            'vehicle_id': self.partner_vehicle_id.id,
            'branch_id': self.warehouse_id.lot_stock_id.id,
            'shop_id': self.shop_id.id,
            'cashier': self.employee_id.id,
            'sale_instruction_ids': [(6, 0, self.instruction_ids.ids)],
        })
        note = ""
        package_lines = self.order_line.filtered(lambda each: each.product_id.is_package)

        component_lines = self.order_line.filtered(lambda each: not each.product_id.is_package and each.product_id.is_component)
        wf_component_lines = component_lines.filtered(lambda each: each.product_id.is_wf_component)
        normal_component_lines = component_lines.filtered(lambda each: not each.product_id.is_wf_component)

        material_lines = self.order_line.filtered(lambda each: not each.product_id.is_package and not each.product_id.is_component)
        if package_lines:
            for line in package_lines:
                self.env['work.order.line'].sudo().create({
                    'work_order_id': work_order.id,
                    'display_type': 'line_section',
                    'name': line.product_id.name,
                })
                if line.customer_note:
                    note += f"<b style='color:blue;'>Package :</b> <b>{line.product_id.name}</b> - <span>{line.customer_note}</span><br/>"
                if line.product_id.is_wf_product:
                    for wf_line in self.workflow_ids:
                        vals = {
                            'work_order_id': work_order.id,
                            'package_id': wf_line.wf_product_id.id,
                            'component_id': wf_line.component_id.product_variant_id.id,
                            'material_id': wf_line.material_id.id,
                            'material_qty': wf_line.material_qty,
                        }
                        self.env['work.order.line'].sudo().create(vals)
                else:
                    for bom_line in line.product_id.bom_line_ids:
                        vals = {
                            'work_order_id': work_order.id,
                            'package_id': bom_line.package_id.id,
                            'component_id': bom_line.component_id.product_variant_id.id,
                            'material_id': bom_line.material_id.id,
                            'material_qty': bom_line.pack_qty,
                        }
                        self.env['work.order.line'].sudo().create(vals)
        if component_lines:
            self.env['work.order.line'].sudo().create({
                'work_order_id': work_order.id,
                'display_type': 'line_section',
                'name': 'Component Sales',
            })
            if wf_component_lines:
                for line in wf_component_lines:
                    if line.customer_note:
                        note += f"<b style='color:green;'>WF Component :</b> <b>{line.product_id.name}</b> - <span>{line.customer_note}</span><br/>"
                for line in self.wf_comp_ids:
                    vals = {
                        'work_order_id': work_order.id,
                        'component_id': line.wf_component_id.id,
                        'material_id': line.material_id.id,
                        'material_qty': line.material_qty,
                    }
                    self.env['work.order.line'].create(vals)
            for line in normal_component_lines:
                if line.customer_note:
                    note += f"<b style='color:green;'>Component :</b> <b>{line.product_id.name}</b> - <span>{line.customer_note}</span><br/>"
                for component_line in line.product_id.component_lines_ids:
                    vals = {
                        'work_order_id': work_order.id,
                        'component_id': component_line.component_id.product_variant_id.id,
                        'material_id': component_line.product_component_id.id,
                        'material_qty': component_line.quty,
                    }
                    self.env['work.order.line'].create(vals)
        if material_lines:
            self.env['work.order.line'].sudo().create({
                'work_order_id': work_order.id,
                'display_type': 'line_section',
                'name': 'Material Sales',
            })
            for line in material_lines:
                if line.customer_note:
                    note += f"<b style='color:red;'>Material :</b> <b>{line.product_id.name}</b> - <span>{line.customer_note}</span><br/>"
                vals = {
                    'work_order_id': work_order.id,
                    'material_id': line.product_id.id,
                    'material_qty': line.product_uom_qty,
                }
                self.env['work.order.line'].create(vals)
        work_order.description = note.strip()
        return {
            'type': 'ir.actions.act_window',
            'target': 'current',
            'name': _('Work Order'),
            'view_mode': 'form',
            'res_model': 'work.order',
            'res_id': work_order.id,
        }

    def action_show_work_order(self):
        """ Function for showing created work orders."""
        value = {
            'domain': [('sale_order_id', '=', self.id)],
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'work.order',
            'type': 'ir.actions.act_window',
            'name': _('Work Order'),
        }
        return value


class SaleOrderLine(models.Model):
    """Inherit the Sale Order Line model to update the _action_launch_stock_rule function."""
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        """
        Launch procurement group run method with required/custom fields generated by a
        sale order line. procurement group will launch '_run_pull', '_run_buy' or '_run_manufacture'
        depending on the sale order line product rule.
        """
        if self._context.get("skip_procurement"):
            return True
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        procurements = []
        for line in self:
            line = line.with_company(line.company_id)
            if line.state != 'sale' or not line.product_id.type in ('consu', 'product'):
                continue
            qty = line._get_qty_procurement(previous_product_uom_qty)
            if float_compare(qty, line.product_uom_qty, precision_digits=precision) == 0:
                continue

            group_id = line._get_procurement_group()
            if not group_id:
                group_id = self.env['procurement.group'].create(line._prepare_procurement_group_vals())
                line.order_id.procurement_group_id = group_id
            else:
                # In case the procurement group is already created and the order was
                # cancelled, we need to update certain values of the group.
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update({'partner_id': line.order_id.partner_shipping_id.id})
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({'move_type': line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)

            values = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty

            line_uom = line.product_uom
            quant_uom = line.product_id.uom_id
            product_qty, procurement_uom = line_uom._adjust_uom_quantities(product_qty, quant_uom)
            # procurements.append(self.env['procurement.group'].Procurement(
            #     line.product_id, product_qty, procurement_uom,
            #     line.order_id.partner_shipping_id.property_stock_customer,
            #     line.product_id.display_name, line.order_id.name, line.order_id.company_id, values))
        if procurements:
            procurement_group = self.env['procurement.group']
            if self.env.context.get('import_file'):
                procurement_group = procurement_group.with_context(import_file=False)
            procurement_group.run(procurements)

        # This next block is currently needed only because the scheduler trigger is done by picking confirmation rather than stock.move confirmation
        orders = self.mapped('order_id')
        for order in orders:
            pickings_to_confirm = order.picking_ids.filtered(lambda p: p.state not in ['cancel', 'done'])
            if pickings_to_confirm:
                # Trigger the Scheduler for Pickings
                pickings_to_confirm.action_confirm()
        return True

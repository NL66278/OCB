##############################################################################
#
# Copyright (c) 2004 TINY SPRL. (http://tiny.be) All Rights Reserved.
#                    Fabien Pinckaers <fp@tiny.Be>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################

from report.interface import report_int
import netsvc

class label_invoices(report_int):
	def create(self, uid, ids, datas, context):
		datas['ids'] = datas['form']['ids']
		self._obj_invoice = netsvc.LocalService('report.account.invoice')
		return self._obj_invoice.create(uid, datas['ids'], datas, context)

	def result(self):
		return self._obj_invoice.result()

		})

label_invoices('report.huissier.label.invoices','huissier.vignettes','addons/auction/report/labels.xml', 'addons/auction/report/labels.xsl')


from django import http
from django.contrib import messages
from django.db import transaction
from django.db.models.functions import Lower
from django.views import generic
from django.urls import reverse
from django.shortcuts import redirect

from editor.models import CustomPartType, CUSTOM_PART_TYPE_PUBLIC_CHOICES, CUSTOM_PART_TYPE_INPUT_WIDGETS, Extension
from editor.forms import NewCustomPartTypeForm, UpdateCustomPartTypeForm, CopyCustomPartTypeForm
from editor.views.generic import AuthorRequiredMixin

import json
import reversion
import traceback

class CreateView(generic.CreateView):
    model = CustomPartType
    form_class = NewCustomPartTypeForm
    template_name = 'custom_part_type/create.html'

    def get_form_kwargs(self):
        kwargs = super(CreateView, self).get_form_kwargs()
        kwargs['author'] = self.request.user
        return kwargs

    def get_success_url(self):
        return self.object.get_absolute_url()

class UpdateView(generic.UpdateView):
    model = CustomPartType
    form_class = UpdateCustomPartTypeForm
    template_name = 'custom_part_type/edit.html'
    context_object_name = 'part_type'

    def post(self, request, *args, **kwargs):
        object = self.get_object()
        if not object.can_be_edited_by(request.user):
            return http.HttpResponseForbidden

        return super(UpdateView, self).post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super(UpdateView, self).get_form_kwargs()
        if self.request.is_ajax and self.request.method == 'POST':
            kwargs.update({
                'data': json.loads(self.request.POST['json'])
            })
        return kwargs

    def form_valid(self, form):
        with transaction.atomic(), reversion.create_revision():
            self.object = form.save(commit=False)
            self.object.extensions.set(form.cleaned_data['extensions'])
            self.object.save()
            reversion.set_user(self.request.user)

        return http.HttpResponse(json.dumps(self.form_valid_response_dict(form)), content_type='application/json')
    
    def form_valid_response_dict(self, form):
        return {'result': 'success'}

    def form_invalid(self, form):
        status = {
            "result": "error",
            "message": "Something went wrong...",
            "traceback": traceback.format_exc(),
            "form_errors": json.dumps(form.errors),
        }
        return http.HttpResponseServerError(json.dumps(status),
                                       content_type='application/json')

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super(UpdateView, self).get_context_data(**kwargs)

        extensions = Extension.objects.filter(public=True) | self.object.extensions.all()
        if not self.request.user.is_anonymous:
            extensions |= Extension.objects.filter(author=self.request.user) 
        extensions = extensions.distinct().order_by(Lower('name'))
        context['extensions'] = [e.as_json() for e in extensions]

        context['editable'] = self.object.can_be_edited_by(self.request.user)
        context['item_json'] = {
            'data': self.object.as_json(), 
            'save_url': self.object.get_absolute_url(), 
            'numbasExtensions': context['extensions']
        }

        return context

class DeleteView(AuthorRequiredMixin, generic.DeleteView):
    model = CustomPartType
    template_name = 'custom_part_type/delete.html'

    def get_success_url(self):
        return reverse('profile_custom_part_types', args=(self.request.user.pk,))

class PublishView(generic.UpdateView):
    model = CustomPartType
    fields = ['published']
    
    def get_success_url(self):
        cpt = self.get_object()
        return reverse('custom_part_type_edit', args=(cpt.pk,)) 

    def dispatch(self, request, *args, **kwargs):
        cpt = self.get_object()
        if cpt.public_availability != 'restricted':
            return http.HttpResponseForbidden
        else:
            return super(PublishView, self).dispatch(request, *args, **kwargs)

    def get(self, *args, **kwargs):
        cpt = self.get_object()
        return redirect(reverse('custom_part_type_edit', args=(cpt.pk,)))

    def post(self, request, *args, **kwargs):
        cpt = self.get_object()
        cpt.public_availability = 'always'
        cpt.save()
        messages.add_message(self.request, messages.SUCCESS, 'This custom part type has been published to the public database.')
        return redirect(self.get_success_url())

class UnPublishView(PublishView):
    def dispatch(self, request, *args, **kwargs):
        cpt = self.get_object()
        if cpt.public_availability == 'restricted':
            return redirect(reverse('custom_part_type_edit', args=(cpt.pk,)))
        else:
            return super(UnPublishView, self).dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        ei = self.get_object()
        ei.unpublish()
        ei.save()
        messages.add_message(self.request, messages.INFO, 'This custom part type has been unpublished from the public database.')
        return redirect(self.get_success_url())

class CopyView(generic.FormView, generic.edit.ModelFormMixin):

    model = CustomPartType
    template_name = 'custom_part_type/copy.html'
    form_class = CopyCustomPartTypeForm

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(CopyView, self).dispatch(request, *args, **kwargs)

    def get_initial(self):
        data = self.initial.copy()
        data['name'] = "{}'s copy of {}".format(self.request.user.first_name, self.object.name)
        return data

    def form_valid(self, form):
        obj = self.get_object()
        if not obj.can_be_copied_by(self.request.user):
            return http.HttpResponseForbidden("You may not copy this custom part type.")

        new_obj = obj.copy(author=self.request.user, name=form.cleaned_data.get('name'))
        new_obj.save()

        return redirect(new_obj.get_absolute_url())

ENV ?= dev
.PHONY: validate bootstrap deploy migrate canary diff status
validate:            ## offline render + schema + istioctl analyze
	scripts/validate.sh
bootstrap:           ## first-time: Istio, cert-manager, TLS, app   (make bootstrap ENV=prod)
	scripts/bootstrap.sh $(ENV)
diff:                ## what would change
	kubectl diff -k k8s/overlays/$(ENV) || true
deploy:              ## apply app manifests, migrate, wait for rollout
	kubectl apply -k k8s/overlays/$(ENV)
	scripts/migrate.sh
	kubectl -n omd rollout status deploy/omd-api
migrate:
	scripts/migrate.sh
canary:              ## make canary P=25
	scripts/canary.sh $(P)
status:
	kubectl -n omd get pods,svc,hpa
	istioctl proxy-status
	istioctl analyze -n omd
